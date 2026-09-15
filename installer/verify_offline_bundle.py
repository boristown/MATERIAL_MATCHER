#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import stat
import sys
from typing import Iterator

MANIFEST_NAME = "offline-manifest.json"
RELEASE_MANIFEST_NAME = "release-manifest.json"
RUNTIME_MANIFEST_NAME = "runtime-manifest.json"
SUPPORTED_FORMAT_VERSION = 1
PRODUCT = "MATERIAL_MATCHER"
RELEASE_PRODUCT = "MATERIAL_MATCHER_RELEASE"
RUNTIME_PRODUCT = "MATERIAL_MATCHER_PYTHON_RUNTIME"
SUPPORTED_ARCHES = {"x86_64", "aarch64"}
RELEASE_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_sha256(root: Path, *, exclude_names: set[str] | None = None) -> str:
    excluded = exclude_names or set()
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file() and not item.is_symlink()):
        if path.name in excluded:
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _normalize_arch(value: str) -> str:
    value = value.lower().strip()
    if value in {"x86_64", "amd64"}:
        return "x86_64"
    if value in {"aarch64", "arm64"}:
        return "aarch64"
    return value


def _safe_relative(value: str) -> PurePosixPath:
    if "\\" in value:
        raise ValueError(f"非法离线包路径：{value!r}")
    path = PurePosixPath(value)
    if not value or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"非法离线包路径：{value!r}")
    return path


def _iter_entries(root: Path) -> Iterator[tuple[str, Path]]:
    def walk(directory: Path, prefix: PurePosixPath | None = None) -> Iterator[tuple[str, Path]]:
        with os.scandir(directory) as iterator:
            entries = sorted(iterator, key=lambda item: item.name)
        for entry in entries:
            relative = PurePosixPath(entry.name) if prefix is None else prefix / entry.name
            path = Path(entry.path)
            if relative.as_posix() == MANIFEST_NAME:
                continue
            if entry.is_symlink():
                yield relative.as_posix(), path
            elif entry.is_dir(follow_symlinks=False):
                yield from walk(path, relative)
            elif entry.is_file(follow_symlinks=False):
                yield relative.as_posix(), path
            else:
                raise ValueError(f"离线包包含不支持的文件类型：{relative.as_posix()}")

    yield from walk(root)


def _validate_symlink(root: Path, relative: str, path: Path, expected_target: str) -> None:
    if not expected_target:
        raise ValueError(f"符号链接缺少目标：{relative}")
    actual_target = os.readlink(path)
    if actual_target != expected_target:
        raise ValueError(f"符号链接目标不一致：{relative}")
    if "\\" in actual_target:
        raise ValueError(f"符号链接目标格式不允许：{relative}")
    target = PurePosixPath(actual_target)
    if target.is_absolute():
        raise ValueError(f"离线包禁止绝对符号链接：{relative}")
    resolved = (path.parent / actual_target).resolve(strict=False)
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"符号链接逃逸离线包目录：{relative}") from exc


def _require_executable(actual: dict[str, Path], relative: str) -> None:
    path = actual[relative]
    if not path.exists() or not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError(f"必需启动文件不可执行：{relative}")


def _native_wheel_exists(expected: dict[str, dict[str, object]], package_prefix: str, target_arch: str) -> bool:
    prefix = f"wheelhouse/{package_prefix.lower()}-"
    return any(
        path.lower().startswith(prefix)
        and path.lower().endswith(".whl")
        and target_arch in PurePosixPath(path).name.lower()
        for path in expected
    )


def _verify_runtime_manifest(root: Path, release_manifest: dict[str, object], target_arch: str) -> dict[str, object]:
    path = root / "release/runtime" / RUNTIME_MANIFEST_NAME
    if not path.is_file():
        raise ValueError(f"离线包缺少 release/runtime/{RUNTIME_MANIFEST_NAME}")
    runtime_manifest = json.loads(path.read_text(encoding="utf-8"))
    if runtime_manifest.get("format_version") != 1 or runtime_manifest.get("product") != RUNTIME_PRODUCT:
        raise ValueError("runtime manifest 产品或格式版本不正确")
    runtime_arch = _normalize_arch(str(runtime_manifest.get("target_arch") or ""))
    if runtime_arch != target_arch:
        raise ValueError("runtime manifest 架构与离线包目标架构不一致")
    runtime_python = str(runtime_manifest.get("python_version") or "").strip()
    if not runtime_python or runtime_python != str(release_manifest.get("python_version") or "").strip():
        raise ValueError("runtime manifest Python 版本与 release manifest 不一致")
    expected_manifest_sha = str(release_manifest.get("runtime_manifest_sha256") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_manifest_sha) or _sha256(path) != expected_manifest_sha:
        raise ValueError("runtime manifest SHA-256 与 release manifest 记录不一致")
    expected_tree_sha = str(runtime_manifest.get("runtime_tree_sha256") or "").lower()
    actual_tree_sha = _tree_sha256(root / "release/runtime", exclude_names={RUNTIME_MANIFEST_NAME})
    if not re.fullmatch(r"[0-9a-f]{64}", expected_tree_sha) or actual_tree_sha != expected_tree_sha:
        raise ValueError("Runtime 文件与 runtime manifest 摘要不一致")
    return runtime_manifest


def _verify_release_manifest(root: Path, manifest: dict[str, object], release_version: str, target_arch: str) -> dict[str, object]:
    path = root / "release" / RELEASE_MANIFEST_NAME
    if not path.is_file():
        raise ValueError(f"离线包缺少 release/{RELEASE_MANIFEST_NAME}")
    release_manifest = json.loads(path.read_text(encoding="utf-8"))
    if release_manifest.get("format_version") != 1 or release_manifest.get("product") != RELEASE_PRODUCT:
        raise ValueError("release manifest 产品或格式版本不正确")
    if str(release_manifest.get("release_version") or "") != release_version:
        raise ValueError("release manifest 版本与离线包版本不一致")
    if _normalize_arch(str(release_manifest.get("target_arch") or "")) != target_arch:
        raise ValueError("release manifest 架构与离线包目标架构不一致")
    expected_sha = str(manifest.get("release_manifest_sha256") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha) or _sha256(path) != expected_sha:
        raise ValueError("release manifest SHA-256 与离线包记录不一致")
    python_version = str(release_manifest.get("python_version") or "").strip()
    source_sha = str(release_manifest.get("source_tree_sha256") or "").lower()
    web_sha = str(release_manifest.get("web_tree_sha256") or "").lower()
    runtime_manifest_sha = str(release_manifest.get("runtime_manifest_sha256") or "").lower()
    if (
        not python_version
        or not re.fullmatch(r"[0-9a-f]{64}", source_sha)
        or not re.fullmatch(r"[0-9a-f]{64}", web_sha)
        or not re.fullmatch(r"[0-9a-f]{64}", runtime_manifest_sha)
    ):
        raise ValueError("release manifest 缺少 Python 版本或 Runtime/源码/前端摘要")
    _verify_runtime_manifest(root, release_manifest, target_arch)
    return release_manifest


def verify_bundle(root: Path, *, skip_arch: bool = False) -> dict[str, object]:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"离线包目录不存在：{root}")
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        raise ValueError(f"缺少 {MANIFEST_NAME}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format_version") != SUPPORTED_FORMAT_VERSION:
        raise ValueError("离线包 manifest 格式版本不受支持")
    if manifest.get("product") != PRODUCT:
        raise ValueError("离线包产品标识不正确")

    release_version = str(manifest.get("release_version") or "").strip()
    if not RELEASE_VERSION_RE.fullmatch(release_version):
        raise ValueError("release_version 只能包含安全的字母、数字、点、下划线、加号和连字符")
    target_arch = _normalize_arch(str(manifest.get("target_arch") or ""))
    if target_arch not in SUPPORTED_ARCHES:
        raise ValueError(f"不支持的目标 CPU 架构：{target_arch or 'empty'}")
    model_id = _safe_relative(str(manifest.get("model_id") or "").strip()).as_posix()
    if not skip_arch and target_arch != _normalize_arch(platform.machine()):
        raise ValueError(f"离线包架构 {target_arch} 与当前机器 {platform.machine()} 不匹配")

    raw_files = manifest.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise ValueError("离线包 manifest files 为空")
    expected: dict[str, dict[str, object]] = {}
    for item in raw_files:
        if not isinstance(item, dict):
            raise ValueError("离线包 manifest files 项格式不正确")
        relative = _safe_relative(str(item.get("path") or "")).as_posix()
        if relative in expected:
            raise ValueError(f"离线包 manifest 路径重复：{relative}")
        expected[relative] = item

    actual = {relative: path for relative, path in _iter_entries(root)}
    missing = sorted(set(expected) - set(actual))
    unexpected = sorted(set(actual) - set(expected))
    if missing:
        raise ValueError(f"离线包缺少文件：{', '.join(missing[:10])}")
    if unexpected:
        raise ValueError(f"离线包包含未登记文件：{', '.join(unexpected[:10])}")

    for relative, item in expected.items():
        path = actual[relative]
        kind = str(item.get("type") or "file")
        if kind == "symlink":
            if not path.is_symlink():
                raise ValueError(f"manifest 声明为符号链接但实际不是：{relative}")
            _validate_symlink(root, relative, path, str(item.get("target") or ""))
            continue
        if kind != "file" or path.is_symlink() or not path.is_file():
            raise ValueError(f"文件类型不一致：{relative}")
        expected_size = int(item.get("size", -1))
        if expected_size < 0 or path.stat().st_size != expected_size:
            raise ValueError(f"文件大小校验失败：{relative}")
        expected_sha = str(item.get("sha256") or "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha) or _sha256(path) != expected_sha:
            raise ValueError(f"SHA-256 校验失败：{relative}")
        if bool(item.get("executable")) and not (stat.S_IMODE(path.stat().st_mode) & 0o111):
            raise ValueError(f"文件缺少可执行权限：{relative}")

    model_prefix = f"models/{model_id}/"
    required_exact = {
        "install.sh",
        "verify_offline_bundle.py",
        "release/release-manifest.json",
        "release/runtime/runtime-manifest.json",
        "release/runtime/bin/python3",
        "release/runtime/bin/material-matcher",
        "release/web/dist/index.html",
        f"models/{model_id}/tokenizer.json",
    }
    missing_required = sorted(required_exact - set(expected))
    if missing_required:
        raise ValueError(f"离线包缺少必需组件：{', '.join(missing_required)}")
    for executable in ("install.sh", "release/runtime/bin/python3", "release/runtime/bin/material-matcher"):
        _require_executable(actual, executable)

    release_manifest = _verify_release_manifest(root, manifest, release_version, target_arch)

    if not any(path in expected for path in (f"models/{model_id}/model_int8.onnx", f"models/{model_id}/model.onnx")):
        raise ValueError(f"离线包缺少 {model_prefix} 下的 ONNX 模型")
    if not _native_wheel_exists(expected, "onnxruntime", target_arch):
        raise ValueError(f"wheelhouse 缺少适用于 {target_arch} 的 onnxruntime wheel")
    if not _native_wheel_exists(expected, "tokenizers", target_arch):
        raise ValueError(f"wheelhouse 缺少适用于 {target_arch} 的 tokenizers wheel")

    return {
        "ok": True,
        "release_version": release_version,
        "target_arch": target_arch,
        "model_id": model_id,
        "python_version": release_manifest["python_version"],
        "file_count": len(expected),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="校验 MATERIAL_MATCHER 正式离线发布目录")
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--skip-arch", action="store_true", help="仅用于构建机预检，不校验当前 CPU 架构")
    args = parser.parse_args()
    try:
        result = verify_bundle(args.bundle, skip_arch=args.skip_arch)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
