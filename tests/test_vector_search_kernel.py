from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from material_matcher.domain.models import MatchingConfig
from material_matcher.embedding.providers import DeterministicEmbeddingProvider
from material_matcher.settings import Settings
from material_matcher.storage.metadata import MetadataRepository
from material_matcher.vector.index import (
    EmbeddedBBQFlatIndex,
    _build_query_score_table,
    _coarse_scores_table,
)


def _global_config(dimensions: int) -> MatchingConfig:
    return MatchingConfig.model_validate({
        "source_id_column": "物料号",
        "scope_mode": "GLOBAL",
        "rules": [
            {"id": "semantic-name", "source": {"fields": ["名称"]}, "target": {"fields": ["名称"]}, "matcher": "semantic", "weight": 60},
        ],
        "retrieval": {"provider": "deterministic_test", "model_id": "deterministic-test-v1", "dimensions": dimensions, "retrieval_top_k": 4, "oversample": 2},
        "decision": {"success_threshold": 60, "review_enabled": True, "review_threshold": 30, "top_n": 2},
    })


def _build_index(tmp_path: Path, rows: int, dimensions: int) -> EmbeddedBBQFlatIndex:
    target = tmp_path / "target.csv"
    lines = ["集团码,名称,型号,组"]
    for index in range(rows):
        lines.append(f"G{index},物料{index},X{index},A")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    settings = Settings(data_dir=tmp_path / "data", config_dir=tmp_path / "etc", log_dir=tmp_path / "log", admin_password="x", embedding_dimensions=dimensions)
    settings.ensure_dirs()
    metadata = MetadataRepository(settings.data_dir / "meta" / "material_matcher.db")
    provider = DeterministicEmbeddingProvider(dimensions)
    service = VectorIndexServiceRef(metadata, settings, provider)
    index = service.build(rows, dimensions)
    return index


class VectorIndexServiceRef:
    """Minimal harness around EmbeddedBBQFlatIndex.build to avoid ingest coupling."""

    def __init__(self, metadata, settings, provider):
        self.metadata = metadata
        self.settings = settings
        self.provider = provider

    def build(self, rows: int, dimensions: int) -> EmbeddedBBQFlatIndex:
        from material_matcher.embedding.cache import EmbeddingCache

        cache = EmbeddingCache(self.settings.embedding_cache_dir, self.provider)
        config = _global_config(dimensions)
        target_rows = [{"集团码": f"G{i}", "名称": f"物料{i}", "型号": f"X{i}", "组": "A"} for i in range(rows)]
        root = self.settings.data_dir / "indexes" / "unit-kernel"
        index, _stats = EmbeddedBBQFlatIndex.build(
            root,
            provider=self.provider,
            cache=cache,
            target_rows=iter(target_rows),
            config=config,
            group_code_column="集团码",
            metadata={"fingerprint": "unit", "dimensions": dimensions, "row_count": rows, "scan_block_rows": 64, "oversample": 2, "coarse_kernel": EmbeddedBBQFlatIndex.COARSE_KERNEL, "algorithm_version": "embedded_bbq_flat_v2"},
            embedding_batch_size=128,
            scan_block_rows=64,
        )
        return index


def test_weighted_byte_lut_is_exact_affine_of_plane_kernel() -> None:
    rng = np.random.default_rng(20260916)
    for dimensions in (32, 37, 64):
        packed_dimensions = (dimensions + 7) // 8
        target_packed = rng.integers(0, 256, size=(300, packed_dimensions), dtype=np.uint8)
        query_q4 = rng.integers(-7, 8, size=dimensions, dtype=np.int8)
        sign_packed, planes, active_counts = EmbeddedBBQFlatIndex._pack_query(query_q4)
        legacy = EmbeddedBBQFlatIndex._coarse_scores_packed(target_packed, sign_packed, planes, active_counts)
        table = _build_query_score_table(query_q4, packed_dimensions)
        modern = _coarse_scores_table(target_packed, table)
        total_weight = int(np.abs(query_q4).sum(dtype=np.int64))
        assert np.array_equal(2 * modern.astype(np.int64) - total_weight, legacy.astype(np.int64)), dimensions


def test_search_many_matches_single_search_sequential_and_parallel(tmp_path: Path) -> None:
    dimensions = 32
    index = _build_index(tmp_path, rows = 500, dimensions=dimensions)
    rng = np.random.default_rng(7)
    queries = rng.random((12, dimensions)).astype(np.float32)
    queries /= np.linalg.norm(queries, axis=1, keepdims=True)
    baseline = [index.search(query, 4, oversample=2) for query in queries]
    sequential = index.search_many(queries, 4, oversample=2, scan_workers=0)
    parallel = index.search_many(queries, 4, oversample=2, scan_workers=3)
    try:
        for expected, got_seq, got_par in zip(baseline, sequential, parallel):
            assert [hit.row_id for hit in got_seq] == [hit.row_id for hit in expected]
            assert [hit.row_id for hit in got_par] == [hit.row_id for hit in expected]
            assert np.allclose([hit.score for hit in got_seq], [hit.score for hit in expected])
            assert np.allclose([hit.score for hit in got_par], [hit.score for hit in expected])
    finally:
        index.close()


def test_records_batch_matches_single_record_reads(tmp_path: Path) -> None:
    dimensions = 32
    index = _build_index(tmp_path, rows=200, dimensions=dimensions)
    records = index.records([150, 3, 42, 3])
    assert set(records) == {150, 3, 42}
    assert records[3] == index.record(3)
    assert records[150]["集团码"] == "G150"
