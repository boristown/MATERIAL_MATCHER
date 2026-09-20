#!/usr/bin/env python3
"""校验 d（Docker 方式）离线介质：文件树 SHA256 + 架构 + 必需组件 + 引擎/Compose/镜像记录。"""
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

MANIFEST_NAME = "docker-manifest.json"
PRODUCT = "MATERIAL_MATCHER_DOCKER_BUNDLE"
FORMAT_VERSION = 1
SUPPORTED_ARCHES = {"x86_64", "aarch64"}
RELEASE_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")

REQUIRED_EXECUTABLES = (
    "run.sh",
    "docker_wizard.sh",
    "install_docker.sh",
    "menu.sh",
    "bootstrap/python/bin/python3",
    "tools/installer_smoke.py",
    "disk_select.sh",
    "rst.sh",
    "stop.sh",
    "del.sh",
    "bk.sh",
)
REQUIRED_FILES = REQUIRED_EXECUTABLES + (
    "rst.sh",
    "stop.sh",
    "del.sh",
    "bk.sh",
    "verify_docker_bundle.py",
    "README.md",
    "doc.md",
    "ops.md",
    "use.md",
    "BUILD_INFO.txt",
    "SHA256SUMS",
    "docker/engine/docker-27.1.1.tgz",
    "docker/compose/docker-compose-linux-x86_64",
    "docker/licenses/lic.txt",
    "compose/compose.yaml",
    "seed/business/manifest.json",
    "seed/business/profiles.json",
    "seed/business/dictionaries.json",
    "smoke/smoke-待匹配数据.xlsx",
    "smoke/smoke-集团标准数据.xlsx",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if "\\" in value or not value or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"非法路径：{value!r}")
    return path


def _iter_entries(root: Path) -> Iterator[tuple[str, Path, str]]:
    def walk(directory: Path, prefix: PurePosixPath | None = None):
        with os.scandir(directory) as iterator:
            entries = sorted(iterator, key=lambda item: item.name)
        for entry in entries:
            relative = PurePosixPath(entry.name) if prefix is None else prefix / entry.name
            path = Path(entry.path)
            if relative.as_posix() in {MANIFEST_NAME}:
                continue
            if entry.is_symlink():
                yield relative.as_posix(), path, "symlink"
            elif entry.is_dir(follow_symlinks=False):
                yield from walk(path, relative)
            elif entry.is_file(follow_symlinks=False):
                yield relative.as_posix(), path, "file"
            else:
                raise ValueError(f"不支持的文件类型：{relative.as_posix()}")
    yield from walk(root)


def verify_bundle(root: Path, *, skip_arch: bool = False) -> dict[str, object]:
    root = root.resolve()
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        raise ValueError(f"缺少 {MANIFEST_NAME}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format_version") != FORMAT_VERSION or manifest.get("product") != PRODUCT:
        raise ValueError("Docker 介质 manifest 产品或格式版本不正确")
    release_version = str(manifest.get("release_version") or "")
    if not RELEASE_VERSION_RE.fullmatch(release_version):
        raise ValueError("release_version 不正确")
    target_arch = str(manifest.get("target_arch") or "")
    if target_arch not in SUPPORTED_ARCHES:
        raise ValueError(f"不支持的目标架构：{target_arch}")
    if not skip_arch and target_arch != platform.machine():
        raise ValueError(f"介质架构 {target_arch} 与本机 {platform.machine()} 不一致")
    if not re.fullmatch(r"[0-9a-f]{40}", str(manifest.get("git_commit") or "")):
        raise ValueError("docker manifest 缺少 40 位 Git commit")
    for key in ("docker_engine_version", "docker_compose_version", "image_ref", "image_tar", "image_tar_sha256", "seed_source_db_sha256"):
        if not str(manifest.get(key) or ""):
            raise ValueError(f"docker manifest 缺少字段 {key}")

    expected: dict[str, dict[str, object]] = {}
    for item in manifest.get("files") or []:
        relative = _safe_relative(str(item.get("path") or "")).as_posix()
        if relative in expected:
            raise ValueError(f"manifest 路径重复：{relative}")
        expected[relative] = item
    if not expected:
        raise ValueError("manifest files 为空")

    actual = {relative: (path, kind) for relative, path, kind in _iter_entries(root)}
    missing = sorted(set(expected) - set(actual))
    unexpected = sorted(set(actual) - set(expected))
    if missing:
        raise ValueError(f"介质缺少文件：{', '.join(missing[:8])}")
    if unexpected:
        raise ValueError(f"介质包含未登记文件：{', '.join(unexpected[:8])}")

    for relative, item in expected.items():
        path, kind = actual[relative]
        if str(item.get("type") or "file") == "symlink" or kind == "symlink":
            if kind != "symlink":
                raise ValueError(f"应为符号链接：{relative}")
            target = os.readlink(path)
            if not target or target.startswith("/") or ".." in PurePosixPath(target).parts:
                raise ValueError(f"不安全符号链接：{relative}")
            continue
        if path.stat().st_size != int(item.get("size", -1)):
            raise ValueError(f"文件大小校验失败：{relative}")
        if not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256") or "")) or _sha256(path) != str(item["sha256"]).lower():
            raise ValueError(f"SHA-256 校验失败：{relative}")
        if bool(item.get("executable")) and not (stat.S_IMODE(path.stat().st_mode) & 0o111):
            raise ValueError(f"缺少可执行权限：{relative}")

    missing_required = sorted(set(REQUIRED_FILES) - set(expected))
    if missing_required:
        raise ValueError(f"缺少必需组件：{', '.join(missing_required)}")
    for executable in REQUIRED_EXECUTABLES:
        path = root / executable
        if not path.is_file() or not os.access(path, os.X_OK):
            raise ValueError(f"必需入口不可执行：{executable}")

    if str(manifest.get("image_tar") or "") not in expected:
        raise ValueError("manifest image_tar 未在文件树中")
    image_entry = expected[str(manifest["image_tar"])]
    if str(image_entry.get("sha256") or "").lower() != str(manifest["image_tar_sha256"]).lower():
        raise ValueError("image tar SHA256 与 manifest 记录不一致")

    seed = json.loads((root / "seed/business/manifest.json").read_text(encoding="utf-8"))
    seed_profiles = seed.get("profiles") or []
    if len(seed_profiles) != 6:
        raise ValueError(f"seed 应包含 6 个正式方案，实际 {len(seed_profiles)}")
    for required_prefix in ("A001", "A002", "A003", "A005", "A006", "A007"):
        if not any(str(item.get("name") or "").startswith(required_prefix) for item in seed_profiles):
            raise ValueError(f"seed 缺少方案 {required_prefix}")
    if str(seed.get("source_db_sha256") or "") != str(manifest.get("seed_source_db_sha256") or ""):
        raise ValueError("seed 来源与 docker manifest 记录不一致")

    build_info = (root / "BUILD_INFO.txt").read_text(encoding="utf-8")
    if release_version not in build_info or target_arch not in build_info:
        raise ValueError("BUILD_INFO.txt 与 manifest 不一致")
    for line in (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, _, relative = line.partition("  ")
        entry = expected.get(relative.strip())
        if entry is None or str(entry.get("sha256") or "").lower() != digest.lower():
            raise ValueError(f"SHA256SUMS 与 manifest 不一致：{relative[:60]}")

    return {"ok": True, "release_version": release_version, "target_arch": target_arch,
            "image_ref": manifest["image_ref"], "docker_engine": manifest["docker_engine_version"],
            "compose": manifest["docker_compose_version"], "file_count": len(expected)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--skip-arch", action="store_true", help="仅构建机预检")
    args = parser.parse_args()
    try:
        result = verify_bundle(args.bundle, skip_arch=args.skip_arch)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
