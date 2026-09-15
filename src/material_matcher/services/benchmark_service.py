from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import shutil
import time
import uuid

import numpy as np

from material_matcher.domain.models import MatchingConfig
from material_matcher.embedding.batching import profile_token_lengths, token_budget_batches
from material_matcher.embedding.cache import EmbeddingCache
from material_matcher.embedding.providers import DeterministicEmbeddingProvider, create_embedding_provider, embedding_runtime_status
from material_matcher.settings import Settings
from material_matcher.storage.metadata import MetadataRepository
from material_matcher.vector.index import EmbeddedBBQFlatIndex


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class BenchmarkService:
    """Operator-facing benchmark service."""

    def __init__(self, metadata: MetadataRepository, settings: Settings) -> None:
        self.meta = metadata
        self.settings = settings

    def runtime_status(self) -> dict[str, object]:
        status = embedding_runtime_status(self.settings)
        status["batch_size"] = self.settings.embedding_batch_size
        status["token_budget"] = self.settings.embedding_token_budget
        return status

    def _record(self, *, run_id: str, kind: str, status: str, parameters: dict[str, object], metrics: dict[str, object], started_at: str, error_message: str | None = None) -> dict[str, object]:
        finished_at = _now()
        with self.meta.connect() as connection:
            connection.execute(
                "INSERT INTO benchmark_runs(run_id,kind,status,parameters,metrics,error_message,started_at,finished_at) VALUES(?,?,?,?,?,?,?,?)",
                (run_id, kind, status, _json(parameters), _json(metrics), error_message, started_at, finished_at),
            )
        return {"run_id": run_id, "kind": kind, "status": status, "parameters": parameters, "metrics": metrics, "error_message": error_message, "started_at": started_at, "finished_at": finished_at}

    def list_runs(self, limit: int = 20) -> list[dict[str, object]]:
        with self.meta.connect() as connection:
            rows = connection.execute("SELECT * FROM benchmark_runs ORDER BY started_at DESC LIMIT ?", (max(1, min(200, int(limit))),)).fetchall()
        result: list[dict[str, object]] = []
        for row in rows:
            item = dict(row)
            item["parameters"] = json.loads(str(item["parameters"]))
            item["metrics"] = json.loads(str(item["metrics"]))
            result.append(item)
        return result

    def run_embedding(self, *, sample_count: int = 1000, batch_size: int | None = None) -> dict[str, object]:
        sample_count = max(16, min(50_000, int(sample_count)))
        active_batch = max(1, min(2048, int(batch_size or self.settings.embedding_batch_size)))
        run_id = uuid.uuid4().hex
        started_at = _now()
        parameters = {
            "sample_count": sample_count,
            "batch_size": active_batch,
            "token_budget": self.settings.embedding_token_budget,
            "provider": self.settings.embedding_provider,
            "model_id": self.settings.embedding_model_id,
            "dimensions": self.settings.embedding_dimensions,
            "max_length": self.settings.embedding_max_length,
            "precision": self.settings.embedding_precision,
        }
        try:
            provider = create_embedding_provider(self.settings)
            warmup = ["工业物料性能预热 电阻 型号 R10"] * min(8, active_batch)
            provider.embed_batched(warmup, max_batch_size=active_batch, token_budget=self.settings.embedding_token_budget)
            texts = [f"工业物料样例 {index:06d} 电阻 型号 R{index % 100:02d} 规格 10K 1%" for index in range(sample_count)]
            raw_lengths = provider.token_lengths(texts)
            profile = profile_token_lengths(raw_lengths)
            clipped_lengths = [max(1, min(int(item), provider.spec.max_length)) for item in raw_lengths]
            plan = token_budget_batches(clipped_lengths, max_batch_size=active_batch, token_budget=self.settings.embedding_token_budget)
            actual_tokens = sum(clipped_lengths)
            padded_tokens = sum(len(batch) * max(clipped_lengths[index] for index in batch) for batch in plan) if plan else 0
            latencies: list[float] = []
            total_started = time.perf_counter()
            for start in range(0, sample_count, active_batch):
                batch = texts[start:start + active_batch]
                batch_started = time.perf_counter()
                vectors = provider.embed_batched(batch, max_batch_size=active_batch, token_budget=self.settings.embedding_token_budget)
                if vectors.shape != (len(batch), provider.spec.dimensions):
                    raise RuntimeError(f"embedding output shape mismatch: {vectors.shape}")
                latencies.append(time.perf_counter() - batch_started)
            elapsed = max(time.perf_counter() - total_started, 1e-9)
            array = np.asarray(latencies, dtype=np.float64)
            throughput = sample_count / elapsed
            metrics = {
                "provider_spec": asdict(provider.spec),
                "elapsed_seconds": round(elapsed, 6),
                "throughput_rows_per_second": round(throughput, 3),
                "batch_latency_p50_ms": round(float(np.percentile(array, 50)) * 1000.0, 3),
                "batch_latency_p95_ms": round(float(np.percentile(array, 95)) * 1000.0, 3),
                "projected_1_100_000_rows_hours": round(1_100_000 / throughput / 3600.0, 3),
                "token_length_profile": profile.to_dict(),
                "planned_micro_batches": len(plan),
                "padding_efficiency": round(actual_tokens / max(1, padded_tokens), 6),
                "measurement_scope": "configured_production_embedding_provider",
            }
            return self._record(run_id=run_id, kind="embedding", status="SUCCESS", parameters=parameters, metrics=metrics, started_at=started_at)
        except Exception as exc:
            self._record(run_id=run_id, kind="embedding", status="FAILED", parameters=parameters, metrics={}, started_at=started_at, error_message=str(exc))
            raise

    def run_vector_kernel(self, *, target_rows: int = 10_000, query_count: int = 100, dimensions: int = 128, top_k: int = 50) -> dict[str, object]:
        target_rows = max(100, min(100_000, int(target_rows)))
        query_count = max(1, min(5_000, int(query_count)))
        dimensions = max(16, min(2048, int(dimensions)))
        top_k = max(1, min(target_rows, min(1000, int(top_k))))
        run_id = uuid.uuid4().hex
        started_at = _now()
        parameters = {"target_rows": target_rows, "query_count": query_count, "dimensions": dimensions, "top_k": top_k, "provider": "deterministic_test"}
        root = self.settings.data_dir / "tmp" / f"benchmark-{run_id}"
        index_root = root / "index"
        try:
            provider = DeterministicEmbeddingProvider(dimensions=dimensions)
            cache = EmbeddingCache(root / "cache", provider, token_budget=self.settings.embedding_token_budget)
            config = MatchingConfig.model_validate({
                "source_id_column": "物料号",
                "rules": [{"id": "semantic", "source": {"fields": ["文本"]}, "target": {"fields": ["文本"]}, "matcher": "semantic", "weight": 100}],
                "decision": {"success_threshold": 88, "review_enabled": True, "review_threshold": 75, "top_n": min(5, top_k)},
                "retrieval": {"mode": "vector", "provider": "deterministic_test", "model_id": "deterministic-test-v1", "dimensions": dimensions, "max_length": 256, "precision": "float32", "source": {"fields": ["文本"]}, "target": {"fields": ["文本"]}, "retrieval_top_k": top_k, "oversample": 4},
            })
            rows = ({"集团码": f"G{index:08d}", "文本": f"工业物料 {index:08d} 型号 M{index % 1000:03d}"} for index in range(target_rows))
            build_started = time.perf_counter()
            index, stats = EmbeddedBBQFlatIndex.build(index_root, provider=provider, cache=cache, target_rows=rows, config=config, group_code_column="集团码", metadata={"benchmark": True, "benchmark_kind": "synthetic_vector_kernel"}, embedding_batch_size=min(512, max(16, self.settings.embedding_batch_size)), scan_block_rows=self.settings.index_scan_block_rows)
            build_seconds = max(time.perf_counter() - build_started, 1e-9)
            query_texts = [f"工业物料 {index * 997 % target_rows:08d} 型号 M{index % 1000:03d}" for index in range(query_count)]
            query_vectors = provider.embed_batched(query_texts, max_batch_size=self.settings.query_batch_size, token_budget=self.settings.embedding_token_budget)
            search_started = time.perf_counter()
            hits_returned = sum(len(index.search(query, top_k)) for query in query_vectors)
            search_seconds = max(time.perf_counter() - search_started, 1e-9)
            disk_bytes = sum(path.stat().st_size for path in index_root.rglob("*") if path.is_file())
            metrics = {
                "build_seconds": round(build_seconds, 6), "build_rows_per_second": round(target_rows / build_seconds, 3),
                "search_seconds": round(search_seconds, 6), "search_queries_per_second": round(query_count / search_seconds, 3),
                "average_hits_returned": round(hits_returned / query_count, 3), "index_disk_bytes": int(disk_bytes),
                "build_stats": asdict(stats), "measurement_scope": "synthetic_vector_kernel_only", "production_performance_claim": False,
            }
            return self._record(run_id=run_id, kind="vector_kernel", status="SUCCESS", parameters=parameters, metrics=metrics, started_at=started_at)
        except Exception as exc:
            self._record(run_id=run_id, kind="vector_kernel", status="FAILED", parameters=parameters, metrics={}, started_at=started_at, error_message=str(exc))
            raise
        finally:
            shutil.rmtree(root, ignore_errors=True)
