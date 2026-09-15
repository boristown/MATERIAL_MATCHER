from __future__ import annotations

from pathlib import Path

import numpy as np

from material_matcher.embedding.batching import profile_token_lengths, token_budget_batches
from material_matcher.embedding.cache import EmbeddingCache
from material_matcher.embedding.providers import DeterministicEmbeddingProvider


def test_token_length_profile_recommends_smallest_p99_bucket() -> None:
    lengths = [20] * 50 + [80] * 45 + [170] * 4 + [300]
    profile = profile_token_lengths(lengths)
    assert profile.count == 100
    assert profile.p50 == 50
    assert profile.p95 == 85
    assert profile.p99 >= 172
    assert profile.recommended_max_length == 192
    assert profile.truncation_rates['128'] == 0.05
    assert profile.truncation_rates['256'] == 0.01


def test_token_budget_batches_cover_once_and_obey_limits() -> None:
    lengths = [200, 10, 190, 20, 180, 30, 170, 40, 160]
    batches = token_budget_batches(lengths, max_batch_size=3, token_budget=360)
    flattened = [index for batch in batches for index in batch]
    assert sorted(flattened) == list(range(len(lengths)))
    assert len(flattened) == len(set(flattened))
    for batch in batches:
        assert len(batch) <= 3
        assert len(batch) * max(lengths[index] for index in batch) <= 360 or len(batch) == 1


def test_bucketed_provider_and_cache_preserve_original_order(tmp_path: Path) -> None:
    provider = DeterministicEmbeddingProvider(32)
    texts = ['x' * 90, 'a', 'm' * 30, 'bb', 'z' * 70, 'ccc']
    reference = provider.embed(texts)
    bucketed = provider.embed_batched(texts, max_batch_size=2, token_budget=100)
    assert np.allclose(reference, bucketed)

    cache = EmbeddingCache(tmp_path / 'cache', provider, token_budget=100)
    first, stats = cache.get_or_embed(texts, 'sig', batch_size=3)
    second, second_stats = cache.get_or_embed(texts, 'sig', batch_size=3)
    assert stats.misses == len(texts)
    assert second_stats.hits == len(texts)
    assert np.allclose(reference, first, atol=1e-3)
    assert np.allclose(first, second, atol=1e-3)
