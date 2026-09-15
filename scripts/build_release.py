#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tomllib

RELEASE_MANIFEST = "release-manifest.json"
RUNTIME_MANIFEST = "runtime-manifest.json"
RELEASE_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
SUPPORTED_ARCHES = {"x86_64", "aarch64"}
REQUIRED_IMPORTS = (
    "fastapi",
    "uvicorn",
    "pydantic",
    "openpyxl",
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


def _tree_sha256(root: Path, *, exclude_names: set[str] | None = None) -> str:
    excluded = exclude_names or set()
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file() and not item.is_symlink()):
        if path.name in excluded:
            continue
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(_sha256(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _paths_overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _validate_tree_symlinks(root: Path) -> None:
    resolved_root = root.resolve()
    for path in root.rglob("*"):
        if not path.is_symlink():
            continue
        target = os.readlink(path)
        if not target or "\\" in target or PurePosixPath(target).is_absolute():
            raise ValueError(f"运行时包含不安全符号链接：{path.relative_to(root)} -> {target!r}")
        resolved = (path.parent / target).resolve(strict=False)
        try:
            resolved.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError(f"运行时符号链接逃逸目录：{path.relative_to(root)}") from exc


def _project_version(repo_root: Path) -> str:
    with (repo_root / "pyproject.toml").open("rb") as stream:
        pyproject = tomllib.load(stream)
    project_version = str(pyproject["project"]["version"])
    init_text = (repo_root / "src/material_matcher/__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']\s*$', init_text, re.MULTILINE)
    if not match:
        raise ValueError("无法读取 material_matcher.__version__")
    runtime_version = match.group(1)
    if project_version != runtime_version:
        raise ValueError(f"项目版本不一致：pyproject={project_version}, __version__={runtime_version}")
    return project_version


def _load_runtime_manifest(runtime_dir: Path) -> dict[str, object]:
    path = runtime_dir / RUNTIME_MANIFEST
    if not path.is_file():
        raise ValueError(f"Runtime 缺少 {RUNTIME_MANIFEST}，请先使用 scripts/prepare_runtime.py 准备")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("format_version") != 1 or payload.get("product") != "MATERIAL_MATCHER_PYTHON_RUNTIME":
        raise ValueError("Runtime manifest 产品或格式版本不正确")
    target_arch = _normalize_arch(str(payload.get("target_arch") or ""))
    if target_arch not in SUPPORTED_ARCHES:
        raise ValueError(f"Runtime manifest 架构不受支持：{target_arch or 'empty'}")
    expected_tree = str(payload.get("runtime_tree_sha256") or "").lower()
    actual_tree = _tree_sha256(runtime_dir, exclude_names={RUNTIME_MANIFEST})
    if not re.fullmatch(r"[0-9a-f]{64}", expected_tree) or actual_tree != expected_tree:
        raise ValueError("Runtime 文件与 runtime-manifest.json 摘要不一致")
    return payload


def _runtime_info(python: Path, app_dir: Path) -> dict[str, str]:
    code = (
        "import json,platform; import material_matcher; "
        "print(json.dumps({'version': material_matcher.__version__, "
        "'arch': platform.machine(), 'python': platform.python_version()}))"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(app_dir) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    result = subprocess.run([str(python), "-c", code], check=True, text=True, capture_output=True, env=env)
    return json.loads(result.stdout.strip())


def _verify_imports(python: Path, app_dir: Path) -> None:
    code = f"import {', '.join(REQUIRED_IMPORTS)}; import material_matcher"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(app_dir) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    subprocess.run([str(python), "-c", code], check=True, env=env)


def build_release(
    *,
    runtime_dir: Path,
    web_dist_dir: Path,
    output_dir: Path,
    release_version: str,
    target_arch: str | None = None,
    force: bool = False,
) -> Path:
    if not RELEASE_VERSION_RE.fullmatch(release_version):
        raise ValueError("release_version 只能包含安全的字母、数字、点、下划线、加号和连字符")

    repo_root = Path(__file__).resolve().parents[1]
    project_version = _project_version(repo_root)
    if release_version != project_version:
        raise ValueError(f"release_version={release_version} 与项目版本 {project_version} 不一致")

    runtime_dir = runtime_dir.resolve()
    web_dist_dir = web_dist_dir.resolve()
    output_dir = output_dir.resolve()
    for source in (runtime_dir, web_dist_dir):
        if not source.is_dir():
            raise ValueError(f"输入目录不存在：{source}")
        if _paths_overlap(output_dir, source):
            raise ValueError(f"输出目录不能与输入目录重叠：{output_dir} / {source}")
    if not (web_dist_dir / "index.html").is_file():
        raise ValueError("web dist 缺少 index.html，请先执行前端 production build")
    _validate_tree_symlinks(runtime_dir)
    runtime_manifest = _load_runtime_manifest(runtime_dir)

    runtime_manifest_arch = _normalize_arch(str(runtime_manifest["target_arch"]))
    expected_arch = _normalize_arch(target_arch or runtime_manifest_arch)
    if expected_arch not in SUPPORTED_ARCHES:
        raise ValueError(f"不支持的目标 CPU 架构：{expected_arch}")
    if runtime_manifest_arch != expected_arch:
        raise ValueError(f"Runtime manifest 架构 {runtime_manifest_arch} 与目标架构 {expected_arch} 不一致")

    if output_dir.exists() and any(output_dir.iterdir()):
        if not force:
            raise ValueError(f"输出目录非空：{output_dir}；如确认覆盖请使用 --force")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    shutil.copytree(runtime_dir, output_dir / "runtime", symlinks=True)
    shutil.copytree(
        repo_root / "src/material_matcher",
        output_dir / "app/material_matcher",
        symlinks=False,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )
    shutil.copytree(web_dist_dir, output_dir / "web/dist", symlinks=False)

    python = output_dir / "runtime/bin/python3"
    launcher = output_dir / "runtime/bin/material-matcher"
    if not python.is_file() or not os.access(python, os.X_OK):
        raise ValueError("自包含 runtime 缺少可执行 runtime/bin/python3")
    if not launcher.is_file() or not os.access(launcher, os.X_OK):
        raise ValueError("自包含 runtime 缺少可执行 runtime/bin/material-matcher")

    _verify_imports(python, output_dir / "app")
    runtime_info = _runtime_info(python, output_dir / "app")
    runtime_arch = _normalize_arch(runtime_info["arch"])
    if runtime_arch != expected_arch:
        raise ValueError(f"runtime 实际架构 {runtime_arch} 与目标架构 {expected_arch} 不一致")
    if str(runtime_manifest.get("python_version") or "") != runtime_info["python"]:
        raise ValueError("Runtime 实际 Python 版本与 runtime manifest 不一致")
    if runtime_info["version"] != release_version:
        raise ValueError(f"release runtime 版本 {runtime_info['version']} 与 {release_version} 不一致")

    subprocess.run([str(launcher), "--help"], check=True, stdout=subprocess.DEVNULL, env={**os.environ, "PYTHONPATH": str(output_dir / "app")})

    runtime_manifest_path = output_dir / "runtime" / RUNTIME_MANIFEST
    manifest = {
        "format_version": 1,
        "product": "MATERIAL_MATCHER_RELEASE",
        "release_version": release_version,
        "target_arch": expected_arch,
        "python_version": runtime_info["python"],
        "runtime_manifest_sha256": _sha256(runtime_manifest_path),
        "source_tree_sha256": _tree_sha256(output_dir / "app"),
        "web_tree_sha256": _tree_sha256(output_dir / "web/dist"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = output_dir / RELEASE_MANIFEST
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description="组装 MATERIAL_MATCHER 自包含 release；不联网、不下载依赖")
    parser.add_argument("--runtime-dir", type=Path, required=True, help="scripts/prepare_runtime.py 生成的正式 Python runtime")
    parser.add_argument("--web-dist-dir", type=Path, required=True, help="Vue production build 输出目录")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--release-version", required=True)
    parser.add_argument("--target-arch", choices=("x86_64", "aarch64"), default=None)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        manifest = build_release(
            runtime_dir=args.runtime_dir,
            web_dist_dir=args.web_dist_dir,
            output_dir=args.output_dir,
            release_version=args.release_version,
            target_arch=args.target_arch,
            force=args.force,
        )
    except Exception as exc:
        print(f"release 构建失败：{exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    print(manifest)


if __name__ == "__main__":
    main()
