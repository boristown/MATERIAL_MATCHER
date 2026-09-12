from __future__ import annotations

import argparse
import json

import uvicorn

from .profile import load_profile
from .settings import Settings


def _cmd_serve(_: argparse.Namespace) -> int:
    settings = Settings.load()
    uvicorn.run("material_matcher.api:app", host=settings.host, port=settings.port, workers=1)
    return 0


def _cmd_validate_profile(args: argparse.Namespace) -> int:
    loaded = load_profile(args.path)
    print(json.dumps({
        "ok": True,
        "name": loaded.document.profile.name,
        "version": loaded.document.profile.version,
        "sha256": loaded.sha256,
        "source_path": loaded.source_path,
    }, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="material-matcher")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="启动 B/S 服务")
    serve.set_defaults(func=_cmd_serve)

    validate = sub.add_parser("validate-profile", help="校验客户配置 Profile")
    validate.add_argument("path")
    validate.set_defaults(func=_cmd_validate_profile)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
