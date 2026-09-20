#!/usr/bin/env python3
"""组装 d（Docker 方式）离线介质（不含任何联网步骤；所有组件来自本地输入并逐一入 manifest）。"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOCKER_COPY_PLAN = (
    ("run.sh", "installer/docker/launch_docker_install.sh", True),
    ("docker_wizard.sh", "installer/docker/docker_wizard.sh", True),
    ("install_docker.sh", "installer/docker/install_docker.sh", True),
    ("menu.sh", "installer/docker/maintain_docker.sh", True),
    ("verify_docker_bundle.py", "installer/docker/verify_docker_bundle.py", False),
    ("README.md", "installer/docker/README_docker.txt", False),
    ("doc.md", "installer/docker/docs/docker-install-manual.md", False),
    ("use.md", "installer/docs/use-manual.md", False),
    ("ops.md", "installer/docker/docs/docker-maintain-manual.md", False),
    ("docker/licenses/lic.txt", "installer/docker/licenses.md", False),
    ("compose/compose.yaml", "installer/docker/compose_reference.yaml", False),
    ("compose/BUILD_TAG", "installer/docker/build_tag.txt", False),
    ("tools/installer_smoke.py", "scripts/installer_smoke.py", True),
    ("disk_select.sh", "installer/disk_select.sh", False),
    ("rst.sh", "installer/docker/ops_restart.sh", True),
    ("stop.sh", "installer/docker/ops_stop.sh", True),
    ("del.sh", "installer/docker/ops_uninstall.sh", True),
    ("bk.sh", "installer/docker/ops_backup_timer.sh", True),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_tree(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_file():
        shutil.copy2(source, target)
        return
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, symlinks=True)


def _iter_files(root: Path):
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            continue
        if path.is_file():
            yield path.relative_to(root).as_posix(), path


def _iter_symlinks(root: Path):
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            yield path.relative_to(root).as_posix(), path


def build(*, output_dir: Path, release_dir: Path, seed_dir: Path, image_tar: Path, image_ref: str,
          image_id: str, engine_tgz: Path, compose_bin: Path, bootstrap_runtime_dir: Path,
          release_version: str, target_arch: str, git_commit: str, seed_source_db_sha256: str,
          docker_engine_version: str, docker_compose_version: str, force: bool = False) -> Path:
    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        if not force:
            raise RuntimeError(f"输出目录非空：{output_dir}")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for target, source, executable in DOCKER_COPY_PLAN:
        src = REPO / source
        if not src.is_file():
            raise RuntimeError(f"仓库缺少 {source}")
        dst = output_dir / target
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        if executable:
            dst.chmod(0o755)

    _copy_tree(engine_tgz, output_dir / "docker/engine/docker-27.1.1.tgz")
    _copy_tree(compose_bin, output_dir / "docker/compose/docker-compose-linux-x86_64")
    (output_dir / "docker/compose/docker-compose-linux-x86_64").chmod(0o755)
    _copy_tree(image_tar, output_dir / "images" / Path(image_tar).name)
    _copy_tree(bootstrap_runtime_dir, output_dir / "bootstrap/python")
    _copy_tree(seed_dir, output_dir / "seed/business")
    shutil.copytree(release_dir / "source", output_dir / "source", symlinks=False,
                    ignore=shutil.ignore_patterns("node_modules", "__pycache__"))
    sys.path.insert(0, str(REPO / "scripts"))
    import generate_smoke_data

    generate_smoke_data.generate(output_dir / "smoke")

    bi = [
        "物料集团码智能匹配平台 · Docker 方式离线安装介质",
        "=========================================",
        f"版本: {release_version}",
        f"Git commit: {git_commit}",
        f"目标架构: {target_arch}",
        "目标系统: 银河麒麟 Linux V10",
        f"构建时间(UTC): {datetime.now(timezone.utc).isoformat()}",
        f"Docker Engine: {docker_engine_version}（官方静态组件 docker-27.1.1.tgz）",
        f"Docker Compose: {docker_compose_version}",
        f"应用镜像: {image_ref} (ID {image_id})",
        f"镜像 tar SHA256: {_sha256(output_dir / 'images' / Path(image_tar).name)}",
        "联网需求: 无（Docker Engine/Compose/镜像/依赖/模型/seed 全部随介质提供）",
        "",
        "安装：终端执行 cd d && ./run.sh，按中文向导操作。",
        "本方式与 n（非 Docker 方式）二选一，不要两个都安装。",
    ]
    (output_dir / "BUILD_INFO.txt").write_text("\n".join(bi) + "\n", encoding="utf-8")

    lines = []
    for relative, path in _iter_files(output_dir):
        if relative == "SHA256SUMS":
            continue
        lines.append(f"{_sha256(path)}  {relative}")
    (output_dir / "SHA256SUMS").write_text("\n".join(sorted(lines)) + "\n", encoding="utf-8")

    files = []
    for relative, path in _iter_symlinks(output_dir):
        target = os.readlink(path)
        if not target or target.startswith("/") or ".." in Path(target).parts:
            raise RuntimeError(f"Docker 介质包含不安全符号链接：{relative} -> {target}")
        files.append({"path": relative, "type": "symlink", "target": target})
    for relative, path in _iter_files(output_dir):
        mode = path.stat().st_mode
        files.append({
            "path": relative,
            "type": "file",
            "size": path.stat().st_size,
            "sha256": _sha256(path),
            "executable": bool(mode & 0o111),
        })
    manifest = {
        "format_version": 1,
        "product": "MATERIAL_MATCHER_DOCKER_BUNDLE",
        "release_version": release_version,
        "target_arch": target_arch,
        "git_commit": git_commit,
        "docker_engine_version": docker_engine_version,
        "docker_compose_version": docker_compose_version,
        "image_ref": image_ref,
        "image_id": image_id,
        "image_tar": "images/" + Path(image_tar).name,
        "image_tar_sha256": _sha256(output_dir / "images" / Path(image_tar).name),
        "seed_source_db_sha256": seed_source_db_sha256,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
    }
    manifest_path = output_dir / "docker-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    subprocess.run([sys.executable, str(output_dir / "verify_docker_bundle.py"), str(output_dir), "--skip-arch"], check=True)
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--seed-dir", type=Path, required=True)
    parser.add_argument("--image-tar", type=Path, required=True)
    parser.add_argument("--image-ref", required=True)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--engine-tgz", type=Path, required=True)
    parser.add_argument("--compose-bin", type=Path, required=True)
    parser.add_argument("--bootstrap-runtime-dir", type=Path, required=True)
    parser.add_argument("--release-version", required=True)
    parser.add_argument("--target-arch", choices=("x86_64", "aarch64"), required=True)
    parser.add_argument("--git-commit", required=True)
    parser.add_argument("--seed-source-db-sha256", required=True)
    parser.add_argument("--docker-engine-version", default="27.1.1")
    parser.add_argument("--docker-compose-version", default="v2.29.7")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    path = build(
        output_dir=args.output_dir, release_dir=args.release_dir, seed_dir=args.seed_dir,
        image_tar=args.image_tar, image_ref=args.image_ref, image_id=args.image_id,
        engine_tgz=args.engine_tgz, compose_bin=args.compose_bin,
        bootstrap_runtime_dir=args.bootstrap_runtime_dir, release_version=args.release_version,
        target_arch=args.target_arch, git_commit=args.git_commit,
        seed_source_db_sha256=args.seed_source_db_sha256,
        docker_engine_version=args.docker_engine_version, docker_compose_version=args.docker_compose_version,
        force=args.force,
    )
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
