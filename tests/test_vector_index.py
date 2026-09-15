from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from material_matcher.domain.models import MatchingConfig
from material_matcher.embedding.cache import EmbeddingCache
from material_matcher.embedding.providers import DeterministicEmbeddingProvider
from material_matcher.embedding.text import retrieval_text_signature
from material_matcher.matching.engine import match_rows_indexed
from material_matcher.settings import Settings
from material_matcher.storage.metadata import MetadataRepository
from material_matcher.vector.index import EmbeddedBBQFlatIndex
from material_matcher.vector.service import VectorIndexService


def _config(weight: int = 60, success: int = 90) -> MatchingConfig:
    return MatchingConfig.model_validate({
        "source_id_column": "物料号",
        "scope_mode": "STRICT",
        "scope": {"source_field": "组", "target_field": "组"},
        "rules": [
            {"id": "semantic-name", "source": {"fields": ["名称"]}, "target": {"fields": ["名称"]}, "matcher": "semantic", "weight": weight},
            {"id": "model", "source": {"fields": ["型号"]}, "target": {"fields": ["型号"]}, "matcher": "exact", "weight": 40},
        ],
        "retrieval": {"provider": "deterministic_test", "model_id": "deterministic-test-v1", "dimensions": 32, "retrieval_top_k": 3, "oversample": 2},
        "decision": {"success_threshold": success, "review_enabled": True, "review_threshold": 50, "top_n": 2},
    })


def test_embedding_cache_and_text_signature_are_reusable(tmp_path: Path) -> None:
    provider = DeterministicEmbeddingProvider(32)
    cache = EmbeddingCache(tmp_path / "cache", provider)
    first, first_stats = cache.get_or_embed(["电阻", "电容", "电阻"], "sig", 2)
    second, second_stats = cache.get_or_embed(["电阻", "电容", "电阻"], "sig", 2)
    assert first_stats.misses == 2
    assert second_stats.hits == 2 and second_stats.misses == 0
    assert np.allclose(first, second, atol=1e-3)
    assert retrieval_text_signature(_config(60, 90), "target") == retrieval_text_signature(_config(20, 80), "target")


def test_packed_popcount_q4_kernel_matches_unpacked_reference() -> None:
    rng = np.random.default_rng(20260915)
    dimensions = 37  # deliberately not divisible by eight; padding bits must not leak into score
    target_positive = rng.integers(0, 2, size=(129, dimensions), dtype=np.uint8)
    target_packed = np.packbits(target_positive, axis=1, bitorder="little")
    query_q4 = rng.integers(-7, 8, size=dimensions, dtype=np.int8)

    sign_packed, magnitude_planes, active_counts = EmbeddedBBQFlatIndex._pack_query(query_q4)
    packed_scores = EmbeddedBBQFlatIndex._coarse_scores_packed(target_packed, sign_packed, magnitude_planes, active_counts)
    reference_signs = target_positive.astype(np.int32) * 2 - 1
    reference_scores = reference_signs @ query_q4.astype(np.int32)

    assert np.array_equal(packed_scores, reference_scores)


def test_bbq_index_reuse_scope_and_indexed_matching(tmp_path: Path) -> None:
    target = tmp_path / "target.csv"
    target.write_text("集团码,名称,型号,组\nG1,电阻,R10,A\nG2,电容,C10,B\nG3,电阻,R11,A\n", encoding="utf-8")
    source = tmp_path / "source.csv"
    source.write_text("物料号,名称,型号,组\n0001,电阻,R10,A\n", encoding="utf-8")
    target_record = {"stored_path": str(target), "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
    settings = Settings(data_dir=tmp_path / "data", config_dir=tmp_path / "etc", log_dir=tmp_path / "log", admin_password="x", embedding_dimensions=32)
    settings.ensure_dirs()
    metadata = MetadataRepository(settings.data_dir / "meta" / "material_matcher.db")
    provider = DeterministicEmbeddingProvider(32)
    service = VectorIndexService(metadata, None, settings, provider_factory=lambda _settings, _config: provider)  # type: ignore[arg-type]
    config = _config()
    index, _, first_info = service.ensure_index(catalog_version_id="catalog-v1", target_file=target_record, group_code_column="集团码", config=config)
    assert first_info["reused"] is False
    assert index.row_count == 3
    assert index.metadata["coarse_kernel"] == EmbeddedBBQFlatIndex.COARSE_KERNEL
    assert index.metadata["format_version"] == 2
    assert (index.root / index.BITS_FILE).stat().st_size == 3 * ((32 + 7) // 8)
    assert (index.root / index.INT8_FILE).stat().st_size == 3 * 32

    reused, _, second_info = service.ensure_index(catalog_version_id="catalog-v1", target_file=target_record, group_code_column="集团码", config=_config(20, 80))
    assert second_info["reused"] is True
    assert reused.root == index.root
    assert len(service.list_versions()) == 1

    cache = EmbeddingCache(settings.embedding_cache_dir, provider)
    rows = match_rows_indexed(source, index=index, provider=provider, cache=cache, config=config, group_code_column="集团码", query_batch_size=2)
    assert rows[0].candidates[0].group_code == "G1"
    assert {item.group_code for item in rows[0].candidates} <= {"G1", "G3"}
