#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import stat
import sys
from typing import Iterator

MANIFEST_NAME = "offline-manifest.json"
SUPPORTED_FORMAT_VERSION = 1
PRODUCT = "MATERIAL_MATCHER"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_arch(value: str) -> str:
    value = value.lower().strip()
    if value in {"x86_64", "amd64"}:
        return "x86_64"
    if value in {"aarch64", "arm64"}:
        return "aarch64"
    return value


def _safe_relative(value: str) -> PurePosixPath:
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
    actual_target = os.readlink(path)
    if actual_target != expected_target:
        raise ValueError(f"符号链接目标不一致：{relative}")
    target = PurePosixPath(actual_target)
    if target.is_absolute():
        raise ValueError(f"离线包禁止绝对符号链接：{relative}")
    resolved = (path.parent / actual_target).resolve(strict=False)
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"符号链接逃逸离线包目录：{relative}") from exc


def verify_bundle(root: Path, *, skip_arch: bool = False) -> dict[str, object]:
    root = root.resolve()
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        raise ValueError(f"缺少 {MANIFEST_NAME}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format_version") != SUPPORTED_FORMAT_VERSION:
        raise ValueError("离线包 manifest 格式版本不受支持")
    if manifest.get("product") != PRODUCT:
        raise ValueError("离线包产品标识不正确")
    release_version = str(manifest.get("release_version") or "").strip()
    target_arch = _normalize_arch(str(manifest.get("target_arch") or ""))
    model_id = str(manifest.get("model_id") or "").strip()
    if not release_version or not target_arch or not model_id:
        raise ValueError("离线包 manifest 缺少 release_version / target_arch / model_id")
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
        if path.stat().st_size != expected_size:
            raise ValueError(f"文件大小校验失败：{relative}")
        expected_sha = str(item.get("sha256") or "").lower()
        if len(expected_sha) != 64 or _sha256(path) != expected_sha:
            raise ValueError(f"SHA-256 校验失败：{relative}")
        if bool(item.get("executable")) and not (stat.S_IMODE(path.stat().st_mode) & 0o111):
            raise ValueError(f"文件缺少可执行权限：{relative}")

    model_prefix = f"models/{model_id}/"
    required_exact = {
        "install.sh",
        "verify_offline_bundle.py",
        "release/runtime/bin/python3",
        "release/runtime/bin/material-matcher",
        "release/web/dist/index.html",
        f"models/{model_id}/tokenizer.json",
    }
    missing_required = sorted(required_exact - set(expected))
    if missing_required:
        raise ValueError(f"离线包缺少必需组件：{', '.join(missing_required)}")
    if not any(path in expected for path in (f"models/{model_id}/model_int8.onnx", f"models/{model_id}/model.onnx")):
        raise ValueError(f"离线包缺少 {model_prefix} 下的 ONNX 模型")
    if not any(path.startswith("wheelhouse/onnxruntime-") and path.endswith(".whl") for path in expected):
        raise ValueError("wheelhouse 缺少 onnxruntime wheel")
    if not any(path.startswith("wheelhouse/tokenizers-") and path.endswith(".whl") for path in expected):
        raise ValueError("wheelhouse 缺少 tokenizers wheel")

    return {
        "ok": True,
        "release_version": release_version,
        "target_arch": target_arch,
        "model_id": model_id,
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
