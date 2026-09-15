from __future__ import annotations

import argparse
import json
import sys

import uvicorn

from material_matcher.api.app import create_app
from material_matcher.api.frontend import attach_frontend
from material_matcher.domain.errors import DomainError
from material_matcher.services.benchmark_service import BenchmarkService
from material_matcher.services.deployment_service import deployment_diagnostics
from material_matcher.settings import Settings
from material_matcher.storage.metadata import MetadataRepository


def _benchmark_service() -> BenchmarkService:
    settings = Settings.load()
    settings.ensure_dirs()
    metadata = MetadataRepository(settings.data_dir / "meta" / "material_matcher.db")
    return BenchmarkService(metadata, settings)


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _serve(host: str, port: int) -> None:
    settings = Settings.load()
    app = create_app(settings)
    attach_frontend(app, settings.web_dist_dir)
    uvicorn.run(app, host=host, port=port)


def main() -> None:
    parser = argparse.ArgumentParser(prog="material-matcher")
    subparsers = parser.add_subparsers(dest="command")

    serve = subparsers.add_parser("serve", help="启动 MATERIAL_MATCHER Web 服务")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=18080)

    doctor = subparsers.add_parser("doctor", help="检查正式部署目录、版本链、前端与 Embedding readiness")
    doctor.add_argument("--require-frontend", action="store_true")
    doctor.add_argument("--require-embedding", action="store_true")
    doctor.add_argument("--require-release-manifest", action="store_true")

    benchmark = subparsers.add_parser("benchmark", help="运行可重复性能基准")
    benchmark_sub = benchmark.add_subparsers(dest="benchmark_kind", required=True)
    embedding = benchmark_sub.add_parser("embedding", help="使用已安装的正式 Embedding Provider 测吞吐")
    embedding.add_argument("--samples", type=int, default=1000)
    embedding.add_argument("--batch-size", type=int, default=None)
    vector = benchmark_sub.add_parser("vector", help="使用确定性向量测实际 BBQ build/search 内核")
    vector.add_argument("--target-rows", type=int, default=10000)
    vector.add_argument("--queries", type=int, default=100)
    vector.add_argument("--dimensions", type=int, default=128)
    vector.add_argument("--top-k", type=int, default=50)

    args = parser.parse_args()
    if args.command in {None, "serve"}:
        host = getattr(args, "host", "0.0.0.0")
        port = getattr(args, "port", 18080)
        _serve(host, port)
        return

    if args.command == "doctor":
        result = deployment_diagnostics(
            Settings.load(),
            require_frontend=bool(args.require_frontend),
            require_embedding=bool(args.require_embedding),
            require_release_manifest=bool(args.require_release_manifest),
        )
        _print(result)
        if not result["ok"]:
            raise SystemExit(2)
        return

    service = _benchmark_service()
    try:
        if args.benchmark_kind == "embedding":
            _print(service.run_embedding(sample_count=args.samples, batch_size=args.batch_size))
        else:
            _print(
                service.run_vector_kernel(
                    target_rows=args.target_rows,
                    query_count=args.queries,
                    dimensions=args.dimensions,
                    top_k=args.top_k,
                )
            )
    except DomainError as exc:
        _print({"error": {"code": exc.code, "message": exc.message, "details": exc.details}})
        raise SystemExit(2) from exc
    except Exception as exc:
        print(f"benchmark failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
