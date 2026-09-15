#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys

MANIFEST_NAME = "offline-manifest.json"
PRODUCT = "MATERIAL_MATCHER"
FORMAT_VERSION = 1


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        if PurePosixPath(target).is_absolute():
            raise ValueError(f"禁止绝对符号链接：{relative}")
        resolved = (path.parent / target).resolve(strict=False)
        try:
            resolved.relative_to(path.parents[len(PurePosixPath(relative).parts) - 1].resolve())
        except (ValueError, IndexError):
            # Full containment is verified again by verify_offline_bundle.py.
            pass
        return {"path": relative, "type": "symlink", "target": target}
    mode = stat.S_IMODE(path.stat().st_mode)
    return {
        "path": relative,
        "type": "file",
        "size": path.stat().st_size,
        "sha256": _sha256(path),
        "executable": bool(mode & 0o111),
    }


def build_bundle(
    *,
    release_dir: Path,
    model_dir: Path,
    wheelhouse_dir: Path,
    output_dir: Path,
    release_version: str,
    target_arch: str,
    model_id: str,
    force: bool = False,
) -> Path:
    release_dir = release_dir.resolve()
    model_dir = model_dir.resolve()
    wheelhouse_dir = wheelhouse_dir.resolve()
    output_dir = output_dir.resolve()
    repo_root = Path(__file__).resolve().parents[1]

    for source in (release_dir, model_dir, wheelhouse_dir):
        if output_dir == source or output_dir in source.parents:
            raise ValueError("输出目录不能覆盖输入目录")
    if output_dir.exists():
        if any(output_dir.iterdir()):
            if not force:
                raise ValueError(f"输出目录非空：{output_dir}；如确认覆盖请使用 --force")
            shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    _copy_tree(release_dir, output_dir / "release")
    model_target = output_dir / "models" / Path(*PurePosixPath(model_id).parts)
    model_target.parent.mkdir(parents=True, exist_ok=True)
    _copy_tree(model_dir, model_target)
    _copy_tree(wheelhouse_dir, output_dir / "wheelhouse")

    shutil.copy2(repo_root / "installer" / "install.sh", output_dir / "install.sh")
    shutil.copy2(repo_root / "installer" / "verify_offline_bundle.py", output_dir / "verify_offline_bundle.py")
    (output_dir / "install.sh").chmod(0o755)

    files = [_entry(relative, path, kind) for relative, path, kind in _iter_entries(output_dir)]
    manifest = {
        "format_version": FORMAT_VERSION,
        "product": PRODUCT,
        "release_version": release_version,
        "target_arch": target_arch,
        "model_id": model_id,
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
    parser.add_argument("--release-dir", type=Path, required=True, help="已构建的自包含 release 目录")
    parser.add_argument("--model-dir", type=Path, required=True, help="目标 Embedding 模型目录，需包含 tokenizer.json 和 ONNX")
    parser.add_argument("--wheelhouse-dir", type=Path, required=True, help="离线 Python wheelhouse")
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
            output_dir=args.output_dir,
            release_version=args.release_version,
            target_arch=args.target_arch,
            model_id=args.model_id,
            force=args.force,
        )
    except Exception as exc:
        print(f"离线包组装失败：{exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    print(manifest)


if __name__ == "__main__":
    main()
