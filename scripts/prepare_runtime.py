#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tomllib

RUNTIME_MANIFEST = "runtime-manifest.json"
SUPPORTED_ARCHES = {"x86_64", "aarch64"}
REQUIRED_IMPORTS = (
    "fastapi",
    "uvicorn",
    "pydantic",
    "openpyxl",
    "xlsxwriter",
    "multipart",
    "numpy",
    "onnxruntime",
    "tokenizers",
)


def _normalize_arch(value: str) -> str:
    value = value.lower().strip()
    if value in {"x86_64", "amd64"}:
        return "x86_64"
    if value in {"aarch64", "arm64"}:
        return "aarch64"
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file() and not item.is_symlink()):
        if path.name == RUNTIME_MANIFEST:
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _paths_overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _validate_symlinks(root: Path) -> None:
    resolved_root = root.resolve()
    for path in root.rglob("*"):
        if not path.is_symlink():
            continue
        target = os.readlink(path)
        if not target or "\\" in target or PurePosixPath(target).is_absolute():
            raise ValueError(f"基础 Runtime 包含不安全符号链接：{path.relative_to(root)} -> {target!r}")
        resolved = (path.parent / target).resolve(strict=False)
        try:
            resolved.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError(f"基础 Runtime 符号链接逃逸目录：{path.relative_to(root)}") from exc


def _dependencies(repo_root: Path) -> list[str]:
    with (repo_root / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)["project"]
    return [*project.get("dependencies", []), *project.get("optional-dependencies", {}).get("embedding", [])]


def _runtime_info(python: Path) -> dict[str, str]:
    code = "import json,platform; print(json.dumps({'python':platform.python_version(),'arch':platform.machine()}))"
    result = subprocess.run([str(python), "-c", code], check=True, text=True, capture_output=True)
    return json.loads(result.stdout.strip())


def _write_launcher(path: Path) -> None:
    path.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "BIN_DIR=$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd)\n"
        "RELEASE_ROOT=$(CDPATH= cd -- \"$BIN_DIR/../..\" && pwd)\n"
        "export PYTHONPATH=\"$RELEASE_ROOT/app${PYTHONPATH:+:$PYTHONPATH}\"\n"
        "exec \"$BIN_DIR/python3\" -m material_matcher.cli \"$@\"\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def prepare_runtime(
    *,
    base_runtime_dir: Path,
    wheelhouse_dir: Path,
    output_dir: Path,
    target_arch: str | None = None,
    force: bool = False,
) -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    base_runtime_dir = base_runtime_dir.resolve()
    wheelhouse_dir = wheelhouse_dir.resolve()
    output_dir = output_dir.resolve()
    for source in (base_runtime_dir, wheelhouse_dir):
        if not source.is_dir():
            raise ValueError(f"输入目录不存在：{source}")
        if _paths_overlap(output_dir, source):
            raise ValueError(f"输出目录不能与输入目录重叠：{output_dir} / {source}")
    _validate_symlinks(base_runtime_dir)

    if output_dir.exists() and any(output_dir.iterdir()):
        if not force:
            raise ValueError(f"输出目录非空：{output_dir}；如确认覆盖请使用 --force")
        shutil.rmtree(output_dir)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(base_runtime_dir, output_dir, symlinks=True)

    python = output_dir / "bin/python3"
    if not python.is_file() or not os.access(python, os.X_OK):
        raise ValueError("基础 Runtime 缺少可执行 bin/python3")

    dependencies = _dependencies(repo_root)
    install_command = [
        str(python),
        "-m",
        "pip",
        "install",
        "--no-index",
        "--disable-pip-version-check",
        "--no-cache-dir",
        "--find-links",
        str(wheelhouse_dir),
        *dependencies,
    ]
    subprocess.run(install_command, check=True)
    subprocess.run([str(python), "-m", "pip", "check"], check=True)
    subprocess.run([str(python), "-c", f"import {', '.join(REQUIRED_IMPORTS)}"], check=True)

    info = _runtime_info(python)
    runtime_arch = _normalize_arch(info["arch"])
    expected_arch = _normalize_arch(target_arch or runtime_arch)
    if expected_arch not in SUPPORTED_ARCHES:
        raise ValueError(f"不支持的目标 CPU 架构：{expected_arch}")
    if runtime_arch != expected_arch:
        raise ValueError(f"Runtime 架构 {runtime_arch} 与目标架构 {expected_arch} 不一致")

    # 启动器属于 Runtime，不允许 build_release 再修改 Runtime 内容。
    _write_launcher(output_dir / "bin/material-matcher")

    manifest = {
        "format_version": 1,
        "product": "MATERIAL_MATCHER_PYTHON_RUNTIME",
        "target_arch": expected_arch,
        "python_version": info["python"],
        "dependencies": dependencies,
        "runtime_tree_sha256": _tree_sha256(output_dir),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = output_dir / RUNTIME_MANIFEST
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description="使用本地 wheelhouse 准备 MATERIAL_MATCHER 自包含 Python Runtime；强制离线")
    parser.add_argument("--base-runtime-dir", type=Path, required=True)
    parser.add_argument("--wheelhouse-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--target-arch", choices=("x86_64", "aarch64"), default=None)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        manifest = prepare_runtime(
            base_runtime_dir=args.base_runtime_dir,
            wheelhouse_dir=args.wheelhouse_dir,
            output_dir=args.output_dir,
            target_arch=args.target_arch,
            force=args.force,
        )
    except Exception as exc:
        print(f"Runtime 准备失败：{exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    print(manifest)


if __name__ == "__main__":
    main()
