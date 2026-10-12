from __future__ import annotations

import argparse
import json
import sys

import uvicorn

from material_matcher.api.app import create_app
from material_matcher.api.frontend import attach_frontend
from material_matcher.domain.errors import DomainError
from material_matcher.services.acceptance_service import AcceptanceService
from material_matcher.services.benchmark_service import BenchmarkService
from material_matcher.services.deployment_service import deployment_diagnostics
from material_matcher.settings import Settings
from material_matcher.storage.metadata import MetadataRepository


def _services() -> tuple[Settings, MetadataRepository]:
    settings = Settings.load()
    settings.ensure_dirs()
    metadata = MetadataRepository(settings.data_dir / "meta" / "material_matcher.db")
    return settings, metadata


def _benchmark_service() -> BenchmarkService:
    settings, metadata = _services()
    return BenchmarkService(metadata, settings)


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _serve(host: str, port: int) -> None:
    # Worker thread runs Python-heavy rerank/persist loops; the default 5ms GIL
    # switch interval starves the API event loop and the UI feels frozen.
    sys.setswitchinterval(0.0005)
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

    acceptance = subparsers.add_parser("acceptance", help="生成证据驱动的生产验收门禁报告")
    acceptance.add_argument("--require-production-ready", action="store_true", help="存在BLOCKED门禁时也返回非零退出码")

    seed_import = subparsers.add_parser("seed-import", help="幂等导入默认业务 seed（6 个正式方案与同义词表）；已存在则跳过，绝不覆盖")
    seed_import.add_argument("--seed-dir", required=True)

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

    rekey = subparsers.add_parser(
        "embedding-rekey",
        help="把旧“方案签名+文本”缓存键迁移为“模型+文本”键：调整比对规则后，未变化的目标文本不再重算向量",
    )
    rekey.add_argument("--profile", required=True, help="变更前方案的 profile_id")
    rekey.add_argument("--version", type=int, default=None, help="变更前方案版本号（默认取该方案最新版本）")
    rekey.add_argument("--dry-run", action="store_true", help="只统计，不写入")

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

    if args.command == "seed-import":
        from pathlib import Path

        from material_matcher.services.business_seed import BusinessSeedService

        settings, metadata = _services()
        try:
            _print(BusinessSeedService(metadata).import_seed(Path(args.seed_dir)))
        except DomainError as exc:
            _print({"error": {"code": exc.code, "message": exc.message, "details": exc.details}})
            raise SystemExit(2) from exc
        return

    if args.command == "embedding-rekey":
        import json as _json

        from material_matcher.domain.models import MatchingConfig
        from material_matcher.embedding.cache import EmbeddingCache
        from material_matcher.embedding.migrate import embedding_rekey
        from material_matcher.embedding.providers import create_embedding_provider

        settings, metadata = _services()
        with metadata.connect() as connection:
            if args.version is not None:
                row = connection.execute(
                    "SELECT document FROM profile_versions WHERE profile_id=? AND version_no=?",
                    (args.profile, int(args.version)),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT document FROM profile_versions WHERE profile_id=? ORDER BY version_no DESC LIMIT 1",
                    (args.profile,),
                ).fetchone()
        if row is None:
            _print({"error": {"code": "PROFILE_VERSION_NOT_FOUND", "message": f"找不到方案版本 {args.profile} @ {args.version or 'latest'}"}})
            raise SystemExit(2)
        config = MatchingConfig.model_validate(_json.loads(str(row["document"])))
        provider = create_embedding_provider(settings)
        report = embedding_rekey(
            index_dir=settings.index_dir,
            cache=EmbeddingCache(settings.embedding_cache_dir, provider),
            config=config,
            dry_run=bool(args.dry_run),
        )
        _print({"profile_id": args.profile, **report})
        if not report["ok"]:
            raise SystemExit(2)
        return
        return

    if args.command == "acceptance":
        settings, metadata = _services()
        result = AcceptanceService(metadata, settings).report()
        _print(result)
        if not result["code_ready"]:
            raise SystemExit(2)
        if bool(args.require_production_ready) and not result["production_ready"]:
            raise SystemExit(3)
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
