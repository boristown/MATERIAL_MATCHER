#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from build_release import build_release


def main() -> None:
    parser = argparse.ArgumentParser(
        description="组装麒麟原生源码版 release；版本直接读取 pyproject.toml，不联网下载依赖"
    )
    parser.add_argument("--runtime-dir", type=Path, required=True, help="由 OpenCode/构建机准备的离线 Python Runtime")
    parser.add_argument("--web-dist-dir", type=Path, required=True, help="已完成的 Vue production dist")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--target-arch", choices=("x86_64", "aarch64"), default=None)
    parser.add_argument("--git-commit", default=None)
    parser.add_argument("--build-time", default=None)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        manifest = build_release(
            runtime_dir=args.runtime_dir,
            web_dist_dir=args.web_dist_dir,
            output_dir=args.output_dir,
            target_arch=args.target_arch,
            git_commit=args.git_commit,
            build_time=args.build_time,
            deployment_mode="native-source",
            force=args.force,
        )
    except Exception as exc:
        print(f"原生源码 release 组装失败：{exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    print(manifest)


if __name__ == "__main__":
    main()
