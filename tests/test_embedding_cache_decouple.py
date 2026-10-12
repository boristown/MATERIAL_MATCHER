from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from material_matcher.domain.models import MatchingConfig
from material_matcher.embedding import providers as providers_module
from material_matcher.embedding.cache import EmbeddingCache
from material_matcher.embedding.migrate import embedding_rekey
from material_matcher.embedding.providers import DeterministicEmbeddingProvider, ParallelEmbeddingProvider
from material_matcher.embedding.text import build_retrieval_text, retrieval_text_signature


def _config() -> MatchingConfig:
    return MatchingConfig.model_validate({
        "rules": [{"id": "name", "source": {"fields": ["名称"]}, "target": {"fields": ["名称"]}, "matcher": "semantic", "weight": 100}],
        "decision": {"success_threshold": 80, "review_enabled": True, "review_threshold": 50, "top_n": 5},
        "retrieval": {"mode": "scan", "retrieval_top_k": 10, "oversample": 2},
        "advanced": {},
    })


def test_legacy_entries_hit_under_same_signature_and_backfill_model_key(tmp_path: Path) -> None:
    provider = DeterministicEmbeddingProvider()
    cache = EmbeddingCache(tmp_path / "cache", provider)
    text = "金属膜电阻 1/4W 10K"
    signature = retrieval_text_signature(_config(), "target")
    vector = provider.embed([text])[0]
    cache.put_many([(cache.key(text, signature), vector)])

    vectors, stats = cache.get_or_embed([text], signature, batch_size=8)
    assert stats.hits == 1 and stats.misses == 0
    assert np.allclose(vectors[0], np.asarray(vector, dtype=np.float32), atol=2e-3)
    # model-scoped key must now exist (backfill on read)
    assert cache.get_many([cache.model_key(text)]).get(cache.model_key(text)) is not None


def test_rekey_allows_plan_edit_without_recompute(tmp_path: Path) -> None:
    """现场工作流：升级后先 embedding-rekey（旧方案），再改规则；未变文本零重算。"""
    provider = DeterministicEmbeddingProvider()
    cache = EmbeddingCache(tmp_path / "cache", provider)
    config = _config()
    text = "金属膜电阻 1/4W 10K"
    old_signature = retrieval_text_signature(config, "target")
    vector = provider.embed([text])[0]
    cache.put_many([(cache.key(text, old_signature), vector)])

    index_root = tmp_path / "indexes" / "idx1"
    index_root.mkdir(parents=True)
    (index_root / "metadata.json").write_text(json.dumps({"target_text_signature": old_signature}), encoding="utf-8")
    (index_root / "records.jsonl").write_text(json.dumps({"名称": text}, ensure_ascii=False) + "\n", encoding="utf-8")
    report = embedding_rekey(index_dir=tmp_path / "indexes", cache=cache, config=config)
    assert report["migrated"] == 1

    edited = MatchingConfig.model_validate({
        "rules": [
            {"id": "name", "source": {"fields": ["名称"]}, "target": {"fields": ["名称"]}, "matcher": "semantic", "weight": 70},
            {"id": "spec", "source": {"fields": ["型号"]}, "target": {"fields": ["型号"]}, "matcher": "exact", "weight": 30},
        ],
        "decision": {"success_threshold": 80, "review_enabled": True, "review_threshold": 50, "top_n": 5},
        "retrieval": {"mode": "scan", "retrieval_top_k": 10, "oversample": 2},
        "advanced": {},
    })
    new_signature = retrieval_text_signature(edited, "target")
    assert new_signature != old_signature
    _vectors, stats = cache.get_or_embed([text], new_signature, batch_size=8)
    assert stats.hits == 1 and stats.misses == 0


def test_get_or_embed_dual_writes_legacy_key(tmp_path: Path) -> None:
    provider = DeterministicEmbeddingProvider()
    cache = EmbeddingCache(tmp_path / "cache", provider)
    text = "去耦电容 0805"
    signature = "sig-x"
    _vectors, stats = cache.get_or_embed([text], signature, batch_size=8)
    assert stats.misses == 1
    assert cache.get_many([cache.key(text, signature)]).get(cache.key(text, signature)) is not None
    assert cache.get_many([cache.model_key(text)]).get(cache.model_key(text)) is not None


def test_embedding_rekey_migrates_index_records(tmp_path: Path) -> None:
    provider = DeterministicEmbeddingProvider()
    cache = EmbeddingCache(tmp_path / "cache", provider)
    config = _config()
    signature = retrieval_text_signature(config, "target")
    rows = [{"名称": "贴片电阻"}, {"名称": "电解电容"}, {"名称": "贴片电阻"}]
    index_root = tmp_path / "indexes" / "idx1"
    index_root.mkdir(parents=True)
    (index_root / "metadata.json").write_text(json.dumps({"target_text_signature": signature}), encoding="utf-8")
    with (index_root / "records.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    for row in rows:
        text = build_retrieval_text(row, config, "target")
        cache.put_many([(cache.key(text, signature), provider.embed([text])[0])])

    dry = embedding_rekey(index_dir=tmp_path / "indexes", cache=cache, config=config, dry_run=True)
    assert dry["migrated"] == 2 and dry["dry_run"] is True
    assert cache.get_many([cache.model_key("贴片电阻")]).get(cache.model_key("贴片电阻")) is None

    result = embedding_rekey(index_dir=tmp_path / "indexes", cache=cache, config=config)
    assert result["unique_texts"] == 2 and result["migrated"] == 2 and result["legacy_vectors_missing"] == 0
    assert cache.get_many([cache.model_key("贴片电阻")]).get(cache.model_key("贴片电阻")) is not None
    again = embedding_rekey(index_dir=tmp_path / "indexes", cache=cache, config=config)
    assert again["migrated"] == 0 and again["already_present"] == 2


def test_parallel_provider_preserves_order_and_values(tmp_path: Path, monkeypatch) -> None:
    model_dir = tmp_path / "bge"
    model_dir.mkdir()
    (model_dir / "model_int8.onnx").write_bytes(b"dummy-model")
    (model_dir / "tokenizer.json").write_text("{}", encoding="utf-8")

    def fake_init(kwargs: dict) -> None:
        providers_module._WORKER_PROVIDER = DeterministicEmbeddingProvider(dimensions=32)

    monkeypatch.setattr(providers_module, "_worker_init", fake_init)
    kwargs = {
        "model_dir": model_dir,
        "model_id": "bge-test",
        "dimensions": 32,
        "max_length": 256,
        "precision": "int8",
        "intra_threads": 1,
        "token_budget": 4096,
    }
    provider = ParallelEmbeddingProvider(kwargs=kwargs, workers=2)
    try:
        texts = [f"物料文本-{index}" for index in range(200)]
        parallel = provider.embed_batched(texts, max_batch_size=8, token_budget=4096)
        reference = DeterministicEmbeddingProvider(dimensions=32).embed_batched(texts, max_batch_size=8, token_budget=4096)
        assert parallel.shape == (200, 32)
        assert np.allclose(parallel, reference, atol=1e-5)
        assert provider.spec.fingerprint == DeterministicEmbeddingProvider(dimensions=32).spec.fingerprint or provider.spec.model_id == "bge-test"
    finally:
        provider.shutdown()
