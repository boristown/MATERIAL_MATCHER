from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from material_matcher.embedding.base import normalize_embeddings
from material_matcher.vector.index import EmbeddedBBQFlatIndex


@dataclass(frozen=True)
class RecallEvaluation:
    reference_rows: int
    query_count: int
    recall_at: dict[int, float]
    top1_hit_rate: float

    def to_dict(self) -> dict[str, object]:
        return {
            "reference_rows": self.reference_rows,
            "query_count": self.query_count,
            "recall_at": {str(k): round(value, 6) for k, value in sorted(self.recall_at.items())},
            "top1_hit_rate": round(self.top1_hit_rate, 6),
            "reference": "float32_exact_cosine",
        }


def _exact_order(reference_vectors: np.ndarray, query_vector: np.ndarray, top_k: int) -> np.ndarray:
    scores = reference_vectors @ query_vector
    keep = min(max(1, int(top_k)), scores.size)
    if keep < scores.size:
        selected = np.argpartition(scores, -keep)[-keep:]
    else:
        selected = np.arange(scores.size, dtype=np.int64)
    return selected[np.argsort(scores[selected], kind="stable")[::-1]]


def evaluate_index_recall(
    index: EmbeddedBBQFlatIndex,
    *,
    reference_vectors: np.ndarray,
    query_vectors: np.ndarray,
    candidate_ids: Sequence[int] | None = None,
    ks: Sequence[int] = (10, 50, 100),
    max_queries: int = 100,
) -> RecallEvaluation:
    references = normalize_embeddings(np.asarray(reference_vectors, dtype=np.float32))
    queries = normalize_embeddings(np.asarray(query_vectors, dtype=np.float32))
    if references.ndim != 2 or queries.ndim != 2:
        raise ValueError("reference_vectors and query_vectors must be 2D")
    if references.shape[1] != queries.shape[1] or references.shape[1] != index.dimensions:
        raise ValueError("embedding dimensions do not match index")
    if candidate_ids is None:
        ids = np.arange(references.shape[0], dtype=np.int64)
    else:
        ids = np.asarray(candidate_ids, dtype=np.int64)
        if ids.ndim != 1 or ids.size != references.shape[0]:
            raise ValueError("candidate_ids must map one-to-one to reference_vectors")
    if ids.size == 0 or queries.shape[0] == 0:
        return RecallEvaluation(reference_rows=int(ids.size), query_count=0, recall_at={}, top1_hit_rate=0.0)
    if np.any(ids < 0) or np.any(ids >= index.row_count):
        raise ValueError("candidate_ids contain rows outside the index")

    active_ks = sorted({int(k) for k in ks if 0 < int(k) <= ids.size})
    if not active_ks:
        raise ValueError("no recall K is valid for the reference set")
    max_k = active_ks[-1]
    query_limit = min(max(1, int(max_queries)), queries.shape[0])
    recall_sums = {k: 0.0 for k in active_ks}
    top1_hits = 0

    for query in queries[:query_limit]:
        exact_local = _exact_order(references, query, max_k)
        exact_global = ids[exact_local]
        approximate = index.search(query, max_k, candidate_ids=ids)
        approximate_ids = np.asarray([hit.row_id for hit in approximate], dtype=np.int64)
        if approximate_ids.size and approximate_ids[0] == exact_global[0]:
            top1_hits += 1
        for k in active_ks:
            expected = set(int(value) for value in exact_global[:k])
            actual = set(int(value) for value in approximate_ids[:k])
            recall_sums[k] += len(expected & actual) / float(k)

    return RecallEvaluation(
        reference_rows=int(ids.size),
        query_count=query_limit,
        recall_at={k: recall_sums[k] / query_limit for k in active_ks},
        top1_hit_rate=top1_hits / query_limit,
    )
