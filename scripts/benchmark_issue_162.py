#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import time
from typing import Any

from material_matcher.domain.models import MatchingConfig
from material_matcher.embedding.cache import EmbeddingCache
from material_matcher.embedding.providers import DeterministicEmbeddingProvider
from material_matcher.matching.engine import RowResult, match_rows_indexed
from material_matcher.services.match_service import MatchService
from material_matcher.settings import Settings
from material_matcher.storage.files import FileRepository
from material_matcher.storage.metadata import MetadataRepository
from material_matcher.vector.service import VectorIndexService


PRESETS = {
    "quick": (1_000, 100_000),
    "stress": (10_000, 1_000_000),
    "formal": (40_000, 1_000_000),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cpu_model() -> str:
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        for line in cpuinfo.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.lower().startswith("model name") and ":" in line:
                return line.split(":", 1)[1].strip()
    return platform.processor() or platform.machine()


def _memory_total_mb() -> float | None:
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        for line in meminfo.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("MemTotal:"):
                return round(int(line.split()[1]) / 1024.0, 1)
    return None


def _gpu_info() -> dict[str, object] | None:
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return {"devices": [line.strip() for line in proc.stdout.splitlines() if line.strip()]}


def _hardware() -> dict[str, object]:
    return {
        "cpu_model": _cpu_model(),
        "cpu_logical_count": os.cpu_count(),
        "ram_mb": _memory_total_mb(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "gpu": _gpu_info(),
    }


def generate_dataset(root: Path, source_rows: int, target_rows: int) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"target-{target_rows}.csv"
    source = root / f"source-{source_rows}-to-{target_rows}.csv"
    if not target.exists():
        with target.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["集团码", "文本", "型号", "类别"])
            for index in range(target_rows):
                writer.writerow([
                    f"G{index:08d}",
                    f"工业物料 {index:08d} 高可靠元件 型号 M{index % 1000:03d} 规格 S{index % 97:02d}",
                    f"M{index % 1000:03d}",
                    f"C{index % 64:02d}",
                ])
    if not source.exists():
        with source.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["物料号", "文本", "型号", "类别", "期望集团码"])
            for index in range(source_rows):
                target_index = (index * 9973 + 17) % target_rows
                writer.writerow([
                    f"S{index:08d}",
                    f"工业物料 {target_index:08d} 高可靠元件 型号 M{target_index % 1000:03d} 规格 S{target_index % 97:02d}",
                    f"M{target_index % 1000:03d}",
                    f"C{target_index % 64:02d}",
                    f"G{target_index:08d}",
                ])
    return source, target


def _config(dimensions: int, top_k: int, top_n: int) -> MatchingConfig:
    return MatchingConfig.model_validate({
        "source_id_column": "物料号",
        "scope_mode": "GLOBAL",
        "rules": [
            {
                "id": "semantic-text",
                "source": {"fields": ["文本"]},
                "target": {"fields": ["文本"]},
                "matcher": "semantic",
                "weight": 70,
            },
            {
                "id": "model",
                "source": {"fields": ["型号"]},
                "target": {"fields": ["型号"]},
                "matcher": "exact",
                "weight": 30,
            },
        ],
        "retrieval": {
            "mode": "vector",
            "provider": "deterministic_test",
            "model_id": "deterministic-test-v1",
            "dimensions": dimensions,
            "max_length": 256,
            "precision": "float32",
            "source": {"fields": ["文本"]},
            "target": {"fields": ["文本"]},
            "retrieval_top_k": top_k,
            "oversample": 4,
        },
        "decision": {
            "success_threshold": 50,
            "review_enabled": True,
            "top_n": top_n,
        },
    })


def _insert_task(metadata: MetadataRepository, task_id: str) -> None:
    with metadata.connect() as connection:
        connection.execute(
            """INSERT OR REPLACE INTO tasks(
                   task_id,name,source_file_id,catalog_version_id,config_snapshot,config_sha256,
                   stage,status,progress,processed_rows,total_rows,created_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (task_id, task_id, "synthetic-source", "synthetic-catalog", "{}", "synthetic",
             "MATCH", "RUNNING", 0.0, 0, 0, "benchmark"),
        )


def _quality(metadata: MetadataRepository, task_id: str, target_rows: int) -> dict[str, object]:
    with metadata.connect() as connection:
        rows = connection.execute(
            "SELECT source_row_id,final_group_code,top1_group_code FROM match_items WHERE task_id=? ORDER BY CAST(source_row_id AS INTEGER)",
            (task_id,),
        ).fetchall()
    correct = 0
    for row in rows:
        source_index = int(row["source_row_id"]) - 1
        target_index = (source_index * 9973 + 17) % target_rows
        expected = f"G{target_index:08d}"
        if str(row["top1_group_code"] or "") == expected:
            correct += 1
    return {
        "rows_checked": len(rows),
        "top1_exact_fixture_accuracy": round(correct / max(1, len(rows)), 6),
        "expected": "1.0 for this exact synthetic fixture",
        "business_accuracy_claim": False,
    }


def run_once(
    *,
    name: str,
    source_path: Path,
    target_path: Path,
    target_rows: int,
    config: MatchingConfig,
    settings: Settings,
    metadata: MetadataRepository,
    indexes: VectorIndexService,
    matcher: MatchService,
    provider: DeterministicEmbeddingProvider,
) -> dict[str, object]:
    task_id = f"bench-{name}"
    _insert_task(metadata, task_id)
    with metadata.connect() as connection:
        connection.execute("DELETE FROM match_candidates WHERE task_id=?", (task_id,))
        connection.execute("DELETE FROM match_items WHERE task_id=?", (task_id,))

    metrics: dict[str, object] = {"timings": {}}
    target_record = {
        "stored_path": str(target_path),
        "sha256": _sha256(target_path),
    }

    wall_started = time.perf_counter()
    cpu_started = time.process_time()
    index_started = time.perf_counter()
    index, _, index_info = indexes.ensure_index(
        catalog_version_id="synthetic-catalog-v1",
        target_file=target_record,
        group_code_column="集团码",
        config=config,
    )
    timings = metrics["timings"]
    assert isinstance(timings, dict)
    timings["target index build/load"] = time.perf_counter() - index_started
    cache = EmbeddingCache(settings.embedding_cache_dir, provider)
    persisted = 0

    def persist(batch: list[RowResult]) -> None:
        nonlocal persisted
        started = time.perf_counter()
        matcher._persist_rows(task_id, batch)
        timings["DB persistence"] = float(timings.get("DB persistence", 0.0)) + (time.perf_counter() - started)
        persisted += len(batch)

    match_rows_indexed(
        source_path,
        index=index,
        provider=provider,
        cache=cache,
        config=config,
        group_code_column="集团码",
        query_batch_size=settings.query_batch_size,
        match_workers=settings.match_workers,
        on_batch=persist,
        batch_rows=settings.match_batch_rows,
        collect_results=False,
        performance_metrics=metrics,
    )
    finalize_started = time.perf_counter()
    quality = _quality(metadata, task_id, target_rows)
    timings["finalize"] = time.perf_counter() - finalize_started

    wall_seconds = max(time.perf_counter() - wall_started, 1e-9)
    cpu_seconds = max(time.process_time() - cpu_started, 0.0)
    def summarize_counts(key: str) -> dict[str, int | float]:
        raw = metrics.pop(key, [])
        values = [int(value) for value in raw] if isinstance(raw, list) else []
        ordered = sorted(values)
        p95 = ordered[max(0, int((len(ordered) * 0.95 + 0.999999)) - 1)] if ordered else 0
        return {
            "total": sum(values),
            "average": round(sum(values) / max(1, len(values)), 3),
            "p95": p95,
            "max": max(values) if values else 0,
        }

    returned_counts = summarize_counts("_candidate_counts")
    pool_counts = summarize_counts("_candidate_pool_counts")
    rerank_counts = summarize_counts("_rerank_counts")
    return {
        "name": name,
        "index_reused": bool(index_info.get("reused")),
        "ann_enabled": bool(index.ann_enabled),
        "source_rows": persisted,
        "target_rows": index.row_count,
        "wall_time_seconds": round(wall_seconds, 6),
        "rows_per_second": round(persisted / wall_seconds, 3),
        "cpu_time_seconds": round(cpu_seconds, 6),
        "worker_count": settings.match_workers,
        "batch_size": settings.match_batch_rows,
        "query_batch_size": settings.query_batch_size,
        "recall_top_k": config.retrieval.retrieval_top_k,
        "persisted_top_n": config.decision.top_n,
        "candidate_count": returned_counts,
        "recall_candidate_pool": pool_counts,
        "vector_rerank_count": rerank_counts,
        "field_scoring_count": returned_counts,
        "ann_fallback_queries": int(metrics.get("ann_fallback_queries", 0)),
        "timings": {key: round(float(value), 6) for key, value in timings.items()},
        "peak_memory_mb": MatchService._peak_memory_mb(),
        "quality": quality,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Issue #162 reproducible bounded-matching benchmark")
    parser.add_argument("--preset", choices=sorted(PRESETS), default="quick")
    parser.add_argument("--source-rows", type=int)
    parser.add_argument("--target-rows", type=int)
    parser.add_argument("--dimensions", type=int, default=32)
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--workers", type=int, default=max(1, min(4, os.cpu_count() or 1)))
    parser.add_argument("--query-batch-size", type=int, default=64)
    parser.add_argument("--persist-batch-size", type=int, default=256)
    parser.add_argument("--warm-runs", type=int, default=1)
    parser.add_argument("--disable-ann", action="store_true", help="Force the legacy full-scan retrieval path for before/after comparison")
    parser.add_argument("--work-dir", type=Path, default=Path(".benchmark/issue-162"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--generate-only", action="store_true")
    parser.add_argument("--keep-work-dir", action="store_true")
    args = parser.parse_args()

    preset_source, preset_target = PRESETS[args.preset]
    source_rows = max(1, args.source_rows or preset_source)
    target_rows = max(1, args.target_rows or preset_target)
    root = args.work_dir.resolve()
    source_path, target_path = generate_dataset(root / "fixtures", source_rows, target_rows)
    if args.generate_only:
        print(json.dumps({
            "source_path": str(source_path),
            "target_path": str(target_path),
            "source_rows": source_rows,
            "target_rows": target_rows,
        }, ensure_ascii=False, indent=2))
        return 0

    settings = Settings(
        data_dir=root / "data",
        config_dir=root / "etc",
        log_dir=root / "log",
        admin_password="benchmark",
        embedding_provider="deterministic_test",
        embedding_model_id="deterministic-test-v1",
        embedding_dimensions=args.dimensions,
        embedding_precision="float32",
        match_workers=max(1, args.workers),
        match_batch_rows=max(1, args.persist_batch_size),
        query_batch_size=max(1, args.query_batch_size),
        ann_min_rows=(target_rows + 1 if args.disable_ann else 100_000),
    )
    settings.ensure_dirs()
    metadata = MetadataRepository(settings.metadata_db_path)
    files = FileRepository(settings.data_dir, metadata)
    provider = DeterministicEmbeddingProvider(args.dimensions)
    config = _config(args.dimensions, args.top_k, args.top_n)
    indexes = VectorIndexService(
        metadata,
        files,
        settings,
        provider_factory=lambda _settings, _config: provider,
    )
    matcher = MatchService(metadata, files, settings, indexes=indexes)

    runs = [
        run_once(
            name="cold",
            source_path=source_path,
            target_path=target_path,
            target_rows=target_rows,
            config=config,
            settings=settings,
            metadata=metadata,
            indexes=indexes,
            matcher=matcher,
            provider=provider,
        )
    ]
    for warm_index in range(max(0, args.warm_runs)):
        runs.append(
            run_once(
                name=f"warm-{warm_index + 1}",
                source_path=source_path,
                target_path=target_path,
                target_rows=target_rows,
                config=config,
                settings=settings,
                metadata=metadata,
                indexes=indexes,
                matcher=matcher,
                provider=provider,
            )
        )

    report: dict[str, Any] = {
        "issue": 162,
        "preset": args.preset,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "hardware": _hardware(),
        "parameters": {
            "source_rows": source_rows,
            "target_rows": target_rows,
            "dimensions": args.dimensions,
            "top_k": args.top_k,
            "top_n": args.top_n,
            "workers": settings.match_workers,
            "query_batch_size": settings.query_batch_size,
            "persist_batch_size": settings.match_batch_rows,
            "retrieval_backend": "legacy_flat_scan" if args.disable_ann else "bounded_ann",
            "ann": {
                "min_rows": settings.ann_min_rows,
                "tables": settings.ann_lsh_tables,
                "bits": settings.ann_lsh_bits,
                "probe_radius": settings.ann_probe_radius,
                "candidate_limit": settings.ann_candidate_limit,
            },
        },
        "runs": runs,
        "formal_acceptance": False,
        "formal_acceptance_reason": (
            "Deterministic synthetic provider/data validate bounded concurrency and regression only; "
            "Issue #162 requires the production model, business data/gold set, and customer-class hardware."
        ),
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if not args.keep_work_dir and args.output is None:
        shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
