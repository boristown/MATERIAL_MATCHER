#!/usr/bin/env python3
"""构建 MATERIAL_MATCHER 正式 Docker 镜像（完全离线）：

FROM scratch + 麒麟 V10 用户空间 rootfs（docker export）+ 自包含 release + 模型。
输出 images/material-matcher-<version>.tar（docker save）与记录（image_ref/image_id/tar sha256）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MODEL_ID_DEFAULT = "BAAI/bge-base-zh-v1.5"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(argv: list[str], **kw) -> subprocess.CompletedProcess:
    print("+ " + " ".join(shlex.quote(a) for a in argv[:6]) + (" …" if len(argv) > 6 else ""), flush=True)
    return subprocess.run(argv, check=True, **kw)


def export_base_rootfs(base_image: Path | None, docker_ref: str | None, workdir: Path) -> Path:
    if base_image is not None:
        return base_image
    container = _run(["docker", "create", docker_ref, "/bin/true"], text=True, capture_output=True).stdout.strip()
    try:
        out = workdir / "base-rootfs.tar"
        with out.open("wb") as sink:
            _run(["docker", "export", container], stdout=sink)
        return out
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True)


def build_image(*, release_dir: Path, model_dir: Path, model_id: str, output_tar: Path,
                image_ref: str, base_rootfs: Path | None, base_image: str,
                workdir: Path) -> dict[str, str]:
    context = workdir / "build-context"
    context.mkdir(parents=True, exist_ok=True)
    rootfs = export_base_rootfs(base_rootfs, base_image, workdir)
    shutil.copy(rootfs, context / "base-rootfs.tar")
    shutil.copytree(release_dir, context / "release", symlinks=True)
    model_target = context / "model" / Path(*model_id.split("/"))
    model_target.parent.mkdir(parents=True, exist_ok=True)
    if model_target.exists():
        shutil.rmtree(model_target)
    shutil.copytree(model_dir, model_target, symlinks=True)
    (context / "Dockerfile").write_text(
        "FROM scratch\n"
        "ADD base-rootfs.tar /\n"
        "ADD release/ /opt/material_matcher/current/\n"
        "ADD model/ /opt/material_matcher/model/\n"
        'ENV HOME=/root PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n'
        'ENV MATERIAL_MATCHER_HOST=0.0.0.0\n'
        'ENV MATERIAL_MATCHER_PORT=18080\n'
        'ENV MATERIAL_MATCHER_DATA_DIR=/var/lib/material_matcher\n'
        'ENV MATERIAL_MATCHER_CONFIG_DIR=/etc/material_matcher\n'
        'ENV MATERIAL_MATCHER_LOG_DIR=/var/log/material_matcher\n'
        'ENV MATERIAL_MATCHER_MODEL_ROOT=/opt/material_matcher/model\n'
        'ENV MATERIAL_MATCHER_WEB_DIST_DIR=/opt/material_matcher/current/web/dist\n'
        "EXPOSE 18080\n"
        'ENTRYPOINT ["/opt/material_matcher/current/runtime/bin/material-matcher"]\n'
        'CMD ["serve"]\n',
        encoding="utf-8",
    )
    _run(["docker", "build", "-t", image_ref, str(context)])
    smoke = subprocess.run(
        ["docker", "run", "--rm", "--network=none", "--entrypoint", "sh",
         "-e", "MATERIAL_MATCHER_DATA_DIR=/tmp/mmcheck", "-e", "MATERIAL_MATCHER_CONFIG_DIR=/tmp/mmcheck",
         "-e", "MATERIAL_MATCHER_LOG_DIR=/tmp/mmcheck",
         image_ref, "-c",
         "mkdir -p /tmp/mmcheck/tmp && exec /opt/material_matcher/current/runtime/bin/material-matcher doctor --require-frontend --require-embedding --require-release-manifest"],
        capture_output=True, text=True,
    )
    if smoke.returncode != 0:
        raise RuntimeError(f"镜像自检（doctor）失败：{smoke.stdout[-400:]}{smoke.stderr[-400:]}")
    image_id = _run(["docker", "inspect", "--format", "{{.Id}}", image_ref], text=True, capture_output=True).stdout.strip()
    output_tar.parent.mkdir(parents=True, exist_ok=True)
    if output_tar.exists():
        output_tar.unlink()
    with output_tar.open("wb") as sink:
        _run(["docker", "save", image_ref], stdout=sink)
    return {"image_ref": image_ref, "image_id": image_id, "image_tar": str(output_tar), "image_tar_sha256": _sha256(output_tar)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--model-id", default=MODEL_ID_DEFAULT)
    parser.add_argument("--output-tar", type=Path, required=True)
    parser.add_argument("--image-ref", required=True, help="例如 material-matcher-app:1.2.0")
    parser.add_argument("--base-rootfs", type=Path, default=None, help="已有 rootfs tar；缺省用 --base-image 导出")
    parser.add_argument("--base-image", default="mm/kylin-v10-snapshot0:20260917")
    parser.add_argument("--workdir", type=Path, default=None)
    parser.add_argument("--record", type=Path, default=None, help="JSON 输出")
    args = parser.parse_args()
    workdir = args.workdir or Path(tempfile.mkdtemp(prefix="mm-image-build-"))
    result = build_image(
        release_dir=args.release_dir, model_dir=args.model_dir, model_id=args.model_id,
        output_tar=args.output_tar, image_ref=args.image_ref, base_rootfs=args.base_rootfs,
        base_image=args.base_image, workdir=workdir,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if args.record:
        args.record.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
