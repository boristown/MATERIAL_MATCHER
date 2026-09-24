#!/usr/bin/env python3
"""组装增量升级包：payload 同步 + SHA256SUMS + manifest + zip（顶层 ASCII 目录名）。"""
from __future__ import annotations
import argparse, hashlib, json, shutil, zipfile
from datetime import datetime, timezone
from pathlib import Path

def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--template-dir", required=True, type=Path)
    ap.add_argument("--release-dir", required=True, type=Path, help="build_release 产物（含 app/ 与 web/dist/）")
    ap.add_argument("--from-version", required=True)
    ap.add_argument("--to-version", required=True)
    ap.add_argument("--git-commit", required=True)
    ap.add_argument("--issues", required=True, help="逗号分隔")
    ap.add_argument("--output-dir", required=True, type=Path)
    args = ap.parse_args()

    top = args.output_dir / f"MATERIAL_MATCHER-incremental-{args.from_version}-to-{args.to_version}"
    if top.exists():
        shutil.rmtree(top)
    shutil.copytree(args.template_dir, top)
    shutil.rmtree(top / "payload", ignore_errors=True)
    (top / "payload" / "backend").mkdir(parents=True)
    shutil.copytree(args.release_dir / "app" / "material_matcher", top / "payload" / "backend" / "material_matcher")
    shutil.copytree(args.release_dir / "web" / "dist", top / "payload" / "web")

    sums = []
    for p in sorted(top.rglob("*")):
        if p.is_file() and p.name != "SHA256SUMS.payload":
            rel = p.relative_to(top).as_posix()
            if rel.startswith(("payload/", "vendor/")):
                sums.append(f"{sha(p)}  {rel}")
    (top / "SHA256SUMS.payload").write_text("\n".join(sums) + "\n", encoding="utf-8")

    files = []
    for p in sorted(top.rglob("*")):
        if p.is_file() and p.name != "manifest.json":
            files.append({"path": p.relative_to(top).as_posix(), "sha256": sha(p), "size": p.stat().st_size})
    manifest = {
        "product": "MATERIAL_MATCHER", "type": "incremental-upgrade",
        "from_versions": [args.from_version], "from_verified": [args.from_version],
        "to_version": args.to_version, "git_commit": args.git_commit,
        "issues": [int(i) for i in args.issues.split(",")],
        "build_time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "db_migration": "startup forward-migration (no manual step; destructive ops prohibited)",
        "package_revision": 1,
    }
    for key in ("README-upgrade.md",):
        pass
    (top / "manifest.json").write_text(json.dumps({**manifest, "files": files}, ensure_ascii=False, indent=1), encoding="utf-8")

    zip_path = args.output_dir / f"MATERIAL_MATCHER-incremental-{args.from_version}-to-{args.to_version}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(top.rglob("*")):
            if p.is_file():
                zf.write(p, f"{top.name}/{p.relative_to(top).as_posix()}")
    (zip_path.with_suffix(".zip.sha256")).write_text(f"{sha(zip_path)}  {zip_path.name}\n", encoding="utf-8")
    print(json.dumps({"zip": str(zip_path), "sha256": sha(zip_path), "files": len(files)}, ensure_ascii=False))

if __name__ == "__main__":
    main()
