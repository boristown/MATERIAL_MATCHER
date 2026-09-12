from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np


POPCOUNT = np.array([int(i).bit_count() for i in range(256)], dtype=np.uint8)


@dataclass
class SearchHit:
    index: int
    item_id: str
    score: float


class EmbeddedBBQFlatIndex:
    """Compact asymmetric binary flat index.

    Target vectors are stored at exactly one bit per dimension (plus small
    global calibration arrays). Queries remain higher precision and are
    quantized to signed 4-bit values at search time. The hot path reduces the
    approximate dot product to packed bitwise AND + popcount operations.

    This is the embedded/offline baseline. A native SIMD implementation can
    replace the NumPy kernel behind the same public interface later.
    """

    def __init__(
        self,
        packed: np.ndarray,
        center: np.ndarray,
        scale: np.ndarray,
        item_ids: list[str],
        dimensions: int,
        rerank_vectors: np.ndarray | None = None,
    ) -> None:
        if packed.dtype != np.uint8 or packed.ndim != 2:
            raise ValueError("packed target vectors must be uint8 matrix")
        if len(item_ids) != packed.shape[0]:
            raise ValueError("item id count does not match vector count")
        self.packed = packed
        self.center = center.astype(np.float32, copy=False)
        self.scale = np.maximum(scale.astype(np.float32, copy=False), 1e-6)
        self.item_ids = item_ids
        self.dimensions = int(dimensions)
        self.rerank_vectors = rerank_vectors

    @property
    def count(self) -> int:
        return int(self.packed.shape[0])

    @property
    def packed_bytes_per_vector(self) -> int:
        return int(self.packed.shape[1])

    @classmethod
    def build(
        cls,
        vectors: np.ndarray,
        item_ids: Iterable[str] | None = None,
        *,
        store_float16_rerank: bool = False,
    ) -> "EmbeddedBBQFlatIndex":
        matrix = np.asarray(vectors, dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[0] == 0 or matrix.shape[1] == 0:
            raise ValueError("vectors must be a non-empty 2D matrix")
        center = matrix.mean(axis=0, dtype=np.float64).astype(np.float32)
        scale = matrix.std(axis=0, dtype=np.float64).astype(np.float32)
        scale[scale < 1e-6] = 1.0
        bits = matrix >= center
        packed = np.packbits(bits, axis=1, bitorder="little")
        ids = list(item_ids) if item_ids is not None else [str(i) for i in range(matrix.shape[0])]
        rerank = matrix.astype(np.float16) if store_float16_rerank else None
        return cls(packed, center, scale, ids, matrix.shape[1], rerank)

    def _query_int4(self, queries: np.ndarray) -> np.ndarray:
        matrix = np.asarray(queries, dtype=np.float32)
        if matrix.ndim == 1:
            matrix = matrix[None, :]
        if matrix.ndim != 2 or matrix.shape[1] != self.dimensions:
            raise ValueError(f"query dimension must be {self.dimensions}")
        z = (matrix - self.center) / self.scale
        z = np.clip(z, -2.5, 2.5)
        return np.rint(z * (7.0 / 2.5)).astype(np.int8)

    @staticmethod
    def _pack_mask(mask: np.ndarray) -> np.ndarray:
        return np.packbits(mask.astype(np.uint8), bitorder="little")

    def _score_one(self, query_int4: np.ndarray, candidate_indices: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
        targets = self.packed if candidate_indices is None else self.packed[candidate_indices]
        magnitudes = np.abs(query_int4).astype(np.uint8)
        positive = query_int4 >= 0
        selected_sum = np.zeros(targets.shape[0], dtype=np.int32)

        # q is signed 4-bit. For sign target t in {-1,+1},
        # dot(t,q) = -sum(q) + 2*sum(q_i where target_bit_i=1).
        # The second term is decomposed into magnitude bit-planes.
        for bit, weight in ((0, 1), (1, 2), (2, 4)):
            plane = ((magnitudes >> bit) & 1).astype(bool)
            pos_mask = self._pack_mask(plane & positive)
            neg_mask = self._pack_mask(plane & ~positive)
            pos_count = POPCOUNT[np.bitwise_and(targets, pos_mask)].sum(axis=1, dtype=np.int32)
            neg_count = POPCOUNT[np.bitwise_and(targets, neg_mask)].sum(axis=1, dtype=np.int32)
            selected_sum += weight * (pos_count - neg_count)

        dot = -int(query_int4.astype(np.int32).sum()) + 2 * selected_sum
        denom = max(1, int(magnitudes.astype(np.int32).sum()))
        normalized = np.clip(dot.astype(np.float32) / float(denom), -1.0, 1.0)
        scores = (normalized + 1.0) * 0.5
        indices = np.arange(self.count, dtype=np.int64) if candidate_indices is None else candidate_indices
        return indices, scores

    def search_batch(
        self,
        queries: np.ndarray,
        top_k: int = 20,
        *,
        candidate_indices: np.ndarray | None = None,
        rerank: bool = False,
        oversample: int = 4,
    ) -> list[list[SearchHit]]:
        q_float = np.asarray(queries, dtype=np.float32)
        if q_float.ndim == 1:
            q_float = q_float[None, :]
        q_int4 = self._query_int4(q_float)
        top_k = max(1, min(int(top_k), len(candidate_indices) if candidate_indices is not None else self.count))
        results: list[list[SearchHit]] = []

        for q_idx, query in enumerate(q_int4):
            indices, scores = self._score_one(query, candidate_indices)
            approx_k = min(len(indices), max(top_k, top_k * max(1, int(oversample)))) if rerank else top_k
            if approx_k >= len(indices):
                chosen = np.argsort(scores)[::-1]
            else:
                partition = np.argpartition(scores, -approx_k)[-approx_k:]
                chosen = partition[np.argsort(scores[partition])[::-1]]

            if rerank and self.rerank_vectors is not None:
                real_indices = indices[chosen]
                target = self.rerank_vectors[real_indices].astype(np.float32)
                query_float = q_float[q_idx]
                query_norm = np.linalg.norm(query_float)
                target_norm = np.linalg.norm(target, axis=1)
                denom = np.maximum(target_norm * max(query_norm, 1e-8), 1e-8)
                exact = (target @ query_float) / denom
                order = np.argsort(exact)[::-1][:top_k]
                hits = [
                    SearchHit(index=int(real_indices[pos]), item_id=self.item_ids[int(real_indices[pos])], score=float((exact[pos] + 1.0) * 0.5))
                    for pos in order
                ]
            else:
                chosen = chosen[:top_k]
                hits = [
                    SearchHit(index=int(indices[pos]), item_id=self.item_ids[int(indices[pos])], score=float(scores[pos]))
                    for pos in chosen
                ]
            results.append(hits)
        return results

    def save(self, directory: str | Path) -> None:
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        np.save(root / "packed.npy", self.packed, allow_pickle=False)
        np.save(root / "center.npy", self.center, allow_pickle=False)
        np.save(root / "scale.npy", self.scale, allow_pickle=False)
        if self.rerank_vectors is not None:
            np.save(root / "rerank_f16.npy", self.rerank_vectors, allow_pickle=False)
        (root / "ids.json").write_text(json.dumps(self.item_ids, ensure_ascii=False), encoding="utf-8")
        (root / "meta.json").write_text(
            json.dumps({"dimensions": self.dimensions, "count": self.count, "format": "bbq-flat-v1"}, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, directory: str | Path, *, mmap: bool = True) -> "EmbeddedBBQFlatIndex":
        root = Path(directory)
        mode = "r" if mmap else None
        packed = np.load(root / "packed.npy", mmap_mode=mode, allow_pickle=False)
        center = np.load(root / "center.npy", mmap_mode=mode, allow_pickle=False)
        scale = np.load(root / "scale.npy", mmap_mode=mode, allow_pickle=False)
        rerank_path = root / "rerank_f16.npy"
        rerank = np.load(rerank_path, mmap_mode=mode, allow_pickle=False) if rerank_path.exists() else None
        ids = json.loads((root / "ids.json").read_text(encoding="utf-8"))
        meta = json.loads((root / "meta.json").read_text(encoding="utf-8"))
        return cls(packed, center, scale, ids, int(meta["dimensions"]), rerank)
