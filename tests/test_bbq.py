from pathlib import Path

import numpy as np

from material_matcher.bbq import EmbeddedBBQFlatIndex


def test_bbq_uses_one_bit_per_target_dimension_and_finds_nearest(tmp_path: Path) -> None:
    rng = np.random.default_rng(7)
    vectors = rng.normal(size=(128, 64)).astype(np.float32)
    vectors /= np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-8)
    ids = [f"M{i:03d}" for i in range(len(vectors))]

    index = EmbeddedBBQFlatIndex.build(vectors, ids, store_float16_rerank=True)
    assert index.packed_bytes_per_vector == 8
    hits = index.search_batch(vectors[[17]], top_k=5, rerank=True)[0]
    assert hits[0].item_id == "M017"

    index.save(tmp_path / "index")
    loaded = EmbeddedBBQFlatIndex.load(tmp_path / "index", mmap=True)
    assert loaded.count == 128
    assert loaded.packed_bytes_per_vector == 8
    loaded_hits = loaded.search_batch(vectors[[17]], top_k=5, rerank=True)[0]
    assert loaded_hits[0].item_id == "M017"


def test_bbq_batch_search_returns_requested_count() -> None:
    rng = np.random.default_rng(9)
    vectors = rng.normal(size=(40, 32)).astype(np.float32)
    index = EmbeddedBBQFlatIndex.build(vectors)
    results = index.search_batch(vectors[:3], top_k=4)
    assert len(results) == 3
    assert all(len(row) == 4 for row in results)
