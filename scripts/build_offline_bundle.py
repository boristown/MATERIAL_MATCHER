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
import stat
import subprocess
import sys

MANIFEST_NAME = "offline-manifest.json"
RELEASE_MANIFEST_NAME = "release-manifest.json"
PRODUCT = "MATERIAL_MATCHER"
FORMAT_VERSION = 1
SUPPORTED_ARCHES = {"x86_64", "aarch64"}
RELEASE_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(value: str, label: str) -> PurePosixPath:
    if "\\" in value:
        raise ValueError(f"{label} 不是安全的相对路径：{value!r}")
    path = PurePosixPath(value)
    if not value or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{label} 不是安全的相对路径：{value!r}")
    return path


def _copy_tree(source: Path, target: Path) -> None:
    if not source.is_dir():
        raise ValueError(f"目录不存在：{source}")
    shutil.copytree(source, target, symlinks=True)


def _iter_entries(root: Path):
    def walk(directory: Path, prefix: PurePosixPath | None = None):
        with os.scandir(directory) as iterator:
            entries = sorted(iterator, key=lambda item: item.name)
        for entry in entries:
            relative = PurePosixPath(entry.name) if prefix is None else prefix / entry.name
            path = Path(entry.path)
            if relative.as_posix() == MANIFEST_NAME:
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


def _entry(relative: str, path: Path, kind: str) -> dict[str, object]:
    if kind == "symlink":
        target = os.readlink(path)
        if not target or "\\" in target or PurePosixPath(target).is_absolute():
            raise ValueError(f"禁止空目标、反斜杠或绝对符号链接：{relative}")
        return {"path": relative, "type": "symlink", "target": target}
    mode = stat.S_IMODE(path.stat().st_mode)
    return {
        "path": relative,
        "type": "file",
        "size": path.stat().st_size,
        "sha256": _sha256(path),
        "executable": bool(mode & 0o111),
    }


def _paths_overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _load_release_manifest(release_dir: Path) -> dict[str, object]:
    path = release_dir / RELEASE_MANIFEST_NAME
    if not path.is_file():
        raise ValueError(f"release 缺少 {RELEASE_MANIFEST_NAME}，请先使用 scripts/build_release.py 构建")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("format_version") != 1 or payload.get("product") != "MATERIAL_MATCHER_RELEASE":
        raise ValueError("release manifest 产品或格式版本不正确")
    return payload


# 介质根目录 → (仓库来源文件, 是否可执行)
ROOT_COPY_PLAN: tuple[tuple[str, str, bool], ...] = (
    ("install.sh", "installer/install.sh", True),
    ("install_wizard.sh", "installer/install_wizard.sh", True),
    ("mmctl", "installer/mmctl", True),
    ("verify_offline_bundle.py", "installer/verify_offline_bundle.py", False),
    ("run.sh", "installer/launch_install.sh", True),
    ("安装物料集团码智能匹配平台.desktop", "installer/desktop_install.desktop", False),
    ("维护物料集团码智能匹配平台.desktop", "installer/desktop_maintain.desktop", False),
    ("menu.sh", "installer/maintain.sh", True),
    ("README.md", "installer/README_first.txt", False),
    ("doc.md", "installer/docs/install-manual.md", False),
    ("docs/doc.md", "installer/docs/install-manual.md", False),
    ("docs/ops.md", "installer/docs/maintain-manual.md", False),
    ("docs/faq.md", "installer/docs/troubleshooting.md", False),
    ("tools/installer_smoke.py", "scripts/installer_smoke.py", True),
    ("disk_select.sh", "installer/disk_select.sh", False),
    ("rst.sh", "installer/native_ops/restart.sh", True),
    ("stop.sh", "installer/native_ops/stop.sh", True),
    ("del.sh", "installer/native_ops/uninstall.sh", True),
    ("bk.sh", "installer/native_ops/backup_timer.sh", True),
)


def _write_build_info(output_dir: Path, *, release_version: str, target_arch: str, model_id: str,
                      git_commit: str, python_version: str, bootstrap_python: str) -> None:
    lines = [
        "物料集团码智能匹配平台 · 正式离线安装介质",
        "=========================================",
        f"版本: {release_version}",
        f"Git commit: {git_commit}",
        f"目标架构: {target_arch}",
        f"目标系统: 银河麒麟 Linux V10",
        f"构建时间(UTC): {datetime.now(timezone.utc).isoformat()}",
        f"应用 Python Runtime: {python_version}",
        f"安装器 bootstrap Python: {bootstrap_python}",
        f"Embedding 模型: {model_id}",
        "联网需求: 无（完全离线安装）",
        "",
        "普通安装人员：终端运行 ./run.sh，按 doc.md 操作（图形桌面可双击安装快捷方式）。",
    ]
    (output_dir / "BUILD_INFO.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_sha256sums(output_dir: Path) -> None:
    lines = []
    for relative, path, kind in _iter_entries(output_dir):
        if kind != "file" or relative == "SHA256SUMS":
            continue
        lines.append(f"{_sha256(path)}  {relative}")
    (output_dir / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _bootstrap_python_version(python: Path) -> str:
    try:
        result = subprocess.run([str(python), "-c", "import platform;print(platform.python_version())"],
                                check=True, text=True, capture_output=True)
        return result.stdout.strip()
    except Exception:
        return "unknown"


def build_bundle(
    *,
    release_dir: Path,
    model_dir: Path,
    wheelhouse_dir: Path,
    bootstrap_runtime_dir: Path,
    output_dir: Path,
    release_version: str,
    target_arch: str,
    model_id: str,
    node_offline_dir: Path | None = None,
    git_commit: str = "",
    force: bool = False,
) -> Path:
    if not RELEASE_VERSION_RE.fullmatch(release_version):
        raise ValueError("release_version 只能包含安全的字母、数字、点、下划线、加号和连字符")
    if target_arch not in SUPPORTED_ARCHES:
        raise ValueError(f"不支持的目标 CPU 架构：{target_arch}")
    model_path = _safe_relative(model_id, "model_id")

    release_dir = release_dir.resolve()
    model_dir = model_dir.resolve()
    wheelhouse_dir = wheelhouse_dir.resolve()
    output_dir = output_dir.resolve()
    repo_root = Path(__file__).resolve().parents[1]

    release_manifest = _load_release_manifest(release_dir)
    if str(release_manifest.get("release_version") or "") != release_version:
        raise ValueError(
            f"release 版本 {release_manifest.get('release_version')} 与离线包版本 {release_version} 不一致"
        )
    if str(release_manifest.get("target_arch") or "") != target_arch:
        raise ValueError(
            f"release 架构 {release_manifest.get('target_arch')} 与离线包目标架构 {target_arch} 不一致"
        )

    for source in (release_dir, model_dir, wheelhouse_dir):
        if _paths_overlap(output_dir, source):
            raise ValueError(f"输出目录不能与输入目录重叠：{output_dir} / {source}")
    if output_dir.exists() and any(output_dir.iterdir()):
        if not force:
            raise ValueError(f"输出目录非空：{output_dir}；如确认覆盖请使用 --force")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    _copy_tree(release_dir, output_dir / "release")
    model_target = output_dir / "models" / Path(*model_path.parts)
    model_target.parent.mkdir(parents=True, exist_ok=True)
    _copy_tree(model_dir, model_target)
    _copy_tree(wheelhouse_dir, output_dir / "wheelhouse")

    bootstrap_runtime_dir = bootstrap_runtime_dir.resolve()
    if not (bootstrap_runtime_dir / "bin/python3").is_file():
        raise ValueError(f"bootstrap runtime 缺少 bin/python3：{bootstrap_runtime_dir}")
    _copy_tree(bootstrap_runtime_dir, output_dir / "bootstrap/python")

    for target, source, executable in ROOT_COPY_PLAN:
        source_path = repo_root / source
        if not source_path.is_file():
            raise ValueError(f"仓库缺少安装介质入口文件：{source}")
        target_path = output_dir / target
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
        if executable:
            target_path.chmod(0o755)

    smoke_script = repo_root / "scripts/generate_smoke_data.py"
    if not smoke_script.is_file():
        raise ValueError("仓库缺少 scripts/generate_smoke_data.py")
    sys.path.insert(0, str(repo_root / "scripts"))
    import generate_smoke_data  # noqa: E402

    generate_smoke_data.generate(output_dir / "smoke")

    if node_offline_dir is not None:
        node_offline_dir = Path(node_offline_dir).resolve()
        if not node_offline_dir.is_dir():
            raise ValueError(f"离线 Node 重建资源目录不存在：{node_offline_dir}")
        _copy_tree(node_offline_dir, output_dir / "tools/node-offline")

    bootstrap_python = output_dir / "bootstrap/python/bin/python3"
    _write_build_info(
        output_dir,
        release_version=release_version,
        target_arch=target_arch,
        model_id=model_path.as_posix(),
        git_commit=git_commit or str(release_manifest.get("git_commit") or "unknown"),
        python_version=str(release_manifest.get("python_version") or ""),
        bootstrap_python=_bootstrap_python_version(bootstrap_python),
    )
    _write_sha256sums(output_dir)

    files = [_entry(relative, path, kind) for relative, path, kind in _iter_entries(output_dir)]
    manifest = {
        "format_version": FORMAT_VERSION,
        "product": PRODUCT,
        "release_version": release_version,
        "target_arch": target_arch,
        "model_id": model_path.as_posix(),
        "release_manifest_sha256": _sha256(output_dir / "release" / RELEASE_MANIFEST_NAME),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
    }
    manifest_path = output_dir / MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    subprocess.run(
        [sys.executable, str(output_dir / "verify_offline_bundle.py"), str(output_dir), "--skip-arch"],
        check=True,
    )
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description="组装 MATERIAL_MATCHER 正式离线发布目录，不下载任何公网依赖")
    parser.add_argument("--release-dir", type=Path, required=True, help="scripts/build_release.py 生成的自包含 release 目录")
    parser.add_argument("--model-dir", type=Path, required=True, help="目标 Embedding 模型目录，需包含 tokenizer.json 和 ONNX")
    parser.add_argument("--wheelhouse-dir", type=Path, required=True, help="离线 Python wheelhouse")
    parser.add_argument("--bootstrap-runtime-dir", type=Path, required=True,
                        help="安装器 bootstrap 自包含 Python（目录内含可执行 bin/python3）")
    parser.add_argument("--node-offline-dir", type=Path, default=None,
                        help="可选：离线前端重建资源（node 运行时 + node_modules 归档）")
    parser.add_argument("--git-commit", default="", help="冻结 commit；缺省读取 release manifest")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--release-version", required=True)
    parser.add_argument("--target-arch", choices=("x86_64", "aarch64"), required=True)
    parser.add_argument("--model-id", default="BAAI/bge-base-zh-v1.5")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        manifest = build_bundle(
            release_dir=args.release_dir,
            model_dir=args.model_dir,
            wheelhouse_dir=args.wheelhouse_dir,
            bootstrap_runtime_dir=args.bootstrap_runtime_dir,
            output_dir=args.output_dir,
            release_version=args.release_version,
            target_arch=args.target_arch,
            model_id=args.model_id,
            node_offline_dir=args.node_offline_dir,
            git_commit=args.git_commit,
            force=args.force,
        )
    except Exception as exc:
        print(f"离线包组装失败：{exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    print(manifest)


if __name__ == "__main__":
    main()
