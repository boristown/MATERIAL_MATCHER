from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable, Protocol

import numpy as np

from .matching import normalize_text


class EmbeddingProvider(Protocol):
    provider_id: str
    dimensions: int

    def encode(self, texts: Iterable[str]) -> np.ndarray: ...


_TOKEN_RE = re.compile(r"[a-z0-9.+/-]+|[\u4e00-\u9fff]+")


@dataclass
class HashingEmbeddingProvider:
    """Small, deterministic, fully-offline retrieval embedding.

    It is intentionally dependency-free and is used as the installation-safe
    fallback. Production profiles can replace it with a local semantic model
    through the same provider interface without changing the BBQ index API.
    """

    dimensions: int = 512
    provider_id: str = "hashing_ngram_v1"

    @staticmethod
    def _features(text: str) -> list[str]:
        normalized = normalize_text(text)
        if not normalized:
            return []
        features: list[str] = []
        for token in _TOKEN_RE.findall(normalized):
            features.append(f"t:{token}")
            if re.search(r"[\u4e00-\u9fff]", token):
                for n in (2, 3):
                    if len(token) >= n:
                        features.extend(f"c{n}:{token[i:i+n]}" for i in range(len(token) - n + 1))
            else:
                compact = token.replace(" ", "")
                for n in (2, 3, 4):
                    if len(compact) >= n:
                        features.extend(f"g{n}:{compact[i:i+n]}" for i in range(len(compact) - n + 1))
        return features

    def _encode_one(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dimensions, dtype=np.float32)
        for feature in self._features(text):
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            raw = int.from_bytes(digest, "little", signed=False)
            index = raw % self.dimensions
            sign = 1.0 if (raw >> 63) == 0 else -1.0
            vector[index] += sign
        norm = float(np.linalg.norm(vector))
        if norm > 0:
            vector /= norm
        return vector

    def encode(self, texts: Iterable[str]) -> np.ndarray:
        rows = [self._encode_one(str(text)) for text in texts]
        if not rows:
            return np.zeros((0, self.dimensions), dtype=np.float32)
        return np.vstack(rows).astype(np.float32, copy=False)


def create_embedding_provider(config: dict | None = None) -> EmbeddingProvider:
    config = config or {}
    provider = str(config.get("provider", "hashing_ngram_v1"))
    if provider == "hashing_ngram_v1":
        return HashingEmbeddingProvider(dimensions=int(config.get("dimensions", 512)))
    raise ValueError(f"unsupported embedding provider: {provider}")
