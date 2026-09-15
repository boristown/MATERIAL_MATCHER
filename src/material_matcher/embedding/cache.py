from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterator, Sequence

import numpy as np

from material_matcher.embedding.base import EmbeddingProvider, normalize_embeddings


@dataclass(frozen=True)
class CacheStats:
    hits: int
    misses: int


class EmbeddingCache:
    """Provider-scoped float16 disk cache with a tiny SQLite offset index."""

    def __init__(self, root: Path, provider: EmbeddingProvider, *, token_budget: int = 0) -> None:
        self.provider = provider
        self.token_budget = max(0, int(token_budget))
        self.root = root / provider.spec.fingerprint
        self.root.mkdir(parents=True, exist_ok=True)
        self.vector_path = self.root / "vectors.f16"
        self.db_path = self.root / "index.sqlite3"
        self._lock = threading.Lock()
        self.lock_path = self.root / "vectors.lock"
        with self._connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS entries(cache_key TEXT PRIMARY KEY, vector_index INTEGER NOT NULL)")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    @staticmethod
    def key(text: str, text_signature: str) -> str:
        return hashlib.sha256((text_signature + "\0" + text).encode("utf-8")).hexdigest()

    def _read(self, vector_index: int) -> np.ndarray:
        item_bytes = self.provider.spec.dimensions * np.dtype(np.float16).itemsize
        with self.vector_path.open("rb") as stream:
            stream.seek(vector_index * item_bytes)
            raw = stream.read(item_bytes)
        if len(raw) != item_bytes:
            raise IOError("embedding cache vector file is truncated")
        return np.frombuffer(raw, dtype=np.float16).astype(np.float32)

    def get_many(self, keys: Sequence[str]) -> dict[str, np.ndarray]:
        if not keys or not self.vector_path.exists():
            return {}
        placeholders = ",".join("?" for _ in keys)
        with self._connect() as connection:
            rows = connection.execute(f"SELECT cache_key, vector_index FROM entries WHERE cache_key IN ({placeholders})", tuple(keys)).fetchall()
        return {str(key): self._read(int(index)) for key, index in rows}

    @contextmanager
    def _process_lock(self) -> Iterator[None]:
        self.lock_path.touch(exist_ok=True)
        with self.lock_path.open("r+b") as lock_stream:
            try:
                import fcntl
                fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
                yield
            finally:
                try:
                    fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)
                except (NameError, OSError):
                    pass

    def put_many(self, items: Sequence[tuple[str, np.ndarray]]) -> None:
        if not items:
            return
        with self._lock, self._process_lock():
            existing = self.get_many([key for key, _ in items])
            pending = [(key, vector) for key, vector in items if key not in existing]
            if not pending:
                return
            item_bytes = self.provider.spec.dimensions * np.dtype(np.float16).itemsize
            self.vector_path.touch(exist_ok=True)
            start_index = self.vector_path.stat().st_size // item_bytes
            rows: list[tuple[str, int]] = []
            with self.vector_path.open("ab") as stream:
                for offset, (key, vector) in enumerate(pending):
                    normalized = normalize_embeddings(np.asarray(vector, dtype=np.float32).reshape(1, -1))[0]
                    if normalized.shape[0] != self.provider.spec.dimensions:
                        raise ValueError("embedding cache dimension mismatch")
                    stream.write(normalized.astype(np.float16).tobytes(order="C"))
                    rows.append((key, start_index + offset))
                stream.flush()
            with self._connect() as connection:
                connection.executemany("INSERT OR IGNORE INTO entries(cache_key,vector_index) VALUES(?,?)", rows)
                connection.commit()

    def get_or_embed(self, texts: Sequence[str], text_signature: str, batch_size: int) -> tuple[np.ndarray, CacheStats]:
        if not texts:
            return np.empty((0, self.provider.spec.dimensions), dtype=np.float32), CacheStats(0, 0)
        keys = [self.key(text, text_signature) for text in texts]
        unique_order: list[str] = []
        text_by_key: dict[str, str] = {}
        for key, text in zip(keys, texts):
            if key not in text_by_key:
                unique_order.append(key); text_by_key[key] = text
        cached = self.get_many(unique_order)
        missing = [key for key in unique_order if key not in cached]
        produced: list[tuple[str, np.ndarray]] = []
        if missing:
            missing_texts = [text_by_key[key] for key in missing]
            budget = self.token_budget or max(1, int(batch_size)) * self.provider.spec.max_length
            embed_batched = getattr(self.provider, "embed_batched", None)
            if callable(embed_batched):
                vectors = embed_batched(missing_texts, max_batch_size=max(1, int(batch_size)), token_budget=budget)
            else:
                parts = []
                for start in range(0, len(missing_texts), max(1, int(batch_size))):
                    parts.append(self.provider.embed(missing_texts[start:start + max(1, int(batch_size))]))
                vectors = np.concatenate(parts, axis=0)
            if vectors.shape != (len(missing), self.provider.spec.dimensions):
                raise ValueError("embedding provider returned unexpected shape")
            for key, vector in zip(missing, vectors):
                cached[key] = vector
                produced.append((key, vector))
        self.put_many(produced)
        result = np.stack([cached[key] for key in keys]).astype(np.float32, copy=False)
        return normalize_embeddings(result), CacheStats(hits=len(unique_order) - len(missing), misses=len(missing))
