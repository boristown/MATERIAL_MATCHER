from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Protocol, Sequence

import numpy as np


@dataclass(frozen=True)
class EmbeddingSpec:
    provider: str
    model_id: str
    dimensions: int
    model_sha256: str
    max_length: int
    normalize: bool = True
    precision: str = "int8"

    @property
    def fingerprint(self) -> str:
        encoded = json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class EmbeddingProvider(Protocol):
    @property
    def spec(self) -> EmbeddingSpec: ...
    def embed(self, texts: Sequence[str]) -> np.ndarray: ...


def normalize_embeddings(vectors: np.ndarray) -> np.ndarray:
    array = np.asarray(vectors, dtype=np.float32)
    if array.ndim != 2:
        raise ValueError("embedding output must be a 2D array")
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return array / norms
