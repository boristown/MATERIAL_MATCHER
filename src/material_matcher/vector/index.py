from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import struct
from typing import Callable, Iterable, Mapping, Sequence
import uuid

import numpy as np

from material_matcher.domain.errors import DomainError
from material_matcher.domain.models import MatchingConfig
from material_matcher.embedding.base import EmbeddingProvider, normalize_embeddings
from material_matcher.embedding.cache import EmbeddingCache
from material_matcher.embedding.text import build_retrieval_text, retrieval_text_signature


@dataclass(frozen=True)
class VectorHit:
    row_id: int
    score: float


@dataclass(frozen=True)
class BuildStats:
    row_count: int
    cache_hits: int
    cache_misses: int


class EmbeddedBBQFlatIndex:
    """1-bit Target + 4-bit Query coarse search with int8 candidate rerank.

    The hot path is block-vectorized with NumPy. It never creates a Source×Target
    matrix and never requires all float32 Target embeddings to exist at once.
    """

    METADATA_FILE = "metadata.json"
    BITS_FILE = "target.bbq.u8"
    INT8_FILE = "target.rerank.i8"
    RECORDS_FILE = "records.jsonl"
    OFFSETS_FILE = "records.offsets.u64"
    POSTINGS_FILE = "scope.postings.json"

    def __init__(self, root: Path) -> None:
        self.root = root
        metadata_path = root / self.METADATA_FILE
        if not metadata_path.exists():
            raise DomainError("INDEX_NOT_FOUND", "向量索引元数据不存在", status_code=404)
        self.metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        self.dimensions = int(self.metadata["dimensions"])
        self.row_count = int(self.metadata["row_count"])
        self.packed_dimensions = (self.dimensions + 7) // 8
        self._bits = np.memmap(root / self.BITS_FILE, dtype=np.uint8, mode="r", shape=(self.row_count, self.packed_dimensions))
        self._int8 = np.memmap(root / self.INT8_FILE, dtype=np.int8, mode="r", shape=(self.row_count, self.dimensions))
        self._offsets = np.memmap(root / self.OFFSETS_FILE, dtype="<u8", mode="r", shape=(self.row_count,))
        postings_path = root / self.POSTINGS_FILE
        self._postings: dict[str, list[int]] = json.loads(postings_path.read_text(encoding="utf-8")) if postings_path.exists() else {}
        self.block_rows = int(self.metadata.get("scan_block_rows", 8192))
        self.oversample = int(self.metadata.get("oversample", 4))

    @classmethod
    def build(
        cls,
        final_root: Path,
        *,
        provider: EmbeddingProvider,
        cache: EmbeddingCache,
        target_rows: Iterable[Mapping[str, object]],
        config: MatchingConfig,
        group_code_column: str,
        metadata: dict[str, object],
        embedding_batch_size: int,
        scan_block_rows: int,
        on_progress: Callable[[int], None] | None = None,
    ) -> tuple["EmbeddedBBQFlatIndex", BuildStats]:
        parent = final_root.parent
        parent.mkdir(parents=True, exist_ok=True)
        temporary = parent / f".{final_root.name}.building-{uuid.uuid4().hex}"
        temporary.mkdir(parents=True, exist_ok=False)
        bits_path = temporary / cls.BITS_FILE
        int8_path = temporary / cls.INT8_FILE
        records_path = temporary / cls.RECORDS_FILE
        offsets_path = temporary / cls.OFFSETS_FILE
        target_signature = retrieval_text_signature(config, "target")
        postings: dict[str, list[int]] = {}
        scope_field = config.scope.target_field if config.scope_mode != "GLOBAL" else None
        row_count = 0; cache_hits = 0; cache_misses = 0

        def flush_batch(batch: list[dict[str, object]], bits_stream, int8_stream, records_stream, offsets_stream) -> None:
            nonlocal row_count, cache_hits, cache_misses
            if not batch:
                return
            texts = [build_retrieval_text(row, config, "target") for row in batch]
            vectors, stats = cache.get_or_embed(texts, target_signature, embedding_batch_size)
            cache_hits += stats.hits; cache_misses += stats.misses
            vectors = normalize_embeddings(vectors)
            packed = np.packbits(vectors >= 0.0, axis=1, bitorder="little")
            packed.tofile(bits_stream)
            quantized = np.clip(np.rint(vectors * 127.0), -127, 127).astype(np.int8)
            quantized.tofile(int8_stream)
            for row in batch:
                offsets_stream.write(struct.pack("<Q", records_stream.tell()))
                records_stream.write((json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
                if scope_field:
                    value = row.get(scope_field)
                    if value is not None:
                        postings.setdefault(str(value), []).append(row_count)
                row_count += 1
            if on_progress:
                on_progress(row_count)

        try:
            with bits_path.open("wb") as bits_stream, int8_path.open("wb") as int8_stream, records_path.open("wb") as records_stream, offsets_path.open("wb") as offsets_stream:
                batch: list[dict[str, object]] = []
                validated_columns = False
                for raw_row in target_rows:
                    row = {str(key): value for key, value in raw_row.items()}
                    if not validated_columns:
                        headers = set(row.keys())
                        missing = [field for rule in config.rules for field in rule.target.fields if field not in headers]
                        if group_code_column not in headers:
                            raise DomainError("COLUMN_NOT_FOUND", f"集团码字段“{group_code_column}”不存在", status_code=422)
                        if missing:
                            raise DomainError("COLUMN_NOT_FOUND", f"集团字段不存在：{', '.join(sorted(set(missing)))}", status_code=422)
                        if config.scope_mode != "GLOBAL" and config.scope.target_field not in headers:
                            raise DomainError("COLUMN_NOT_FOUND", f"集团分类字段“{config.scope.target_field}”不存在", status_code=422)
                        if config.retrieval.target:
                            retrieval_missing = [field for field in config.retrieval.target.fields if field not in headers]
                            if retrieval_missing:
                                raise DomainError("COLUMN_NOT_FOUND", f"向量检索集团字段不存在：{', '.join(retrieval_missing)}", status_code=422)
                        validated_columns = True
                    code = row.get(group_code_column)
                    if code is None or str(code) == "":
                        continue
                    text = build_retrieval_text(row, config, "target")
                    if text == "":
                        continue
                    batch.append(row)
                    if len(batch) >= embedding_batch_size:
                        flush_batch(batch, bits_stream, int8_stream, records_stream, offsets_stream); batch = []
                flush_batch(batch, bits_stream, int8_stream, records_stream, offsets_stream)
            if row_count == 0:
                raise DomainError("INDEX_EMPTY", "集团目录没有可用于向量索引的有效记录", status_code=422)
            (temporary / cls.POSTINGS_FILE).write_text(json.dumps(postings, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            full_metadata = {
                **metadata,
                "format_version": 1,
                "algorithm": "embedded_bbq_flat",
                "row_count": row_count,
                "dimensions": provider.spec.dimensions,
                "target_bits": 1,
                "query_bits": 4,
                "rerank": "int8",
                "scan_block_rows": scan_block_rows,
                "oversample": config.retrieval.oversample,
                "target_text_signature": target_signature,
                "scope_target_field": scope_field,
                "created_at": datetime.now().astimezone().isoformat(),
                "cache_hits": cache_hits,
                "cache_misses": cache_misses,
            }
            (temporary / cls.METADATA_FILE).write_text(json.dumps(full_metadata, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
            if final_root.exists():
                shutil.rmtree(final_root)
            os.replace(temporary, final_root)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return cls(final_root), BuildStats(row_count=row_count, cache_hits=cache_hits, cache_misses=cache_misses)

    def _coarse_scores(self, row_ids: np.ndarray, query_q4: np.ndarray) -> np.ndarray:
        packed = np.asarray(self._bits[row_ids])
        unpacked = np.unpackbits(packed, axis=1, count=self.dimensions, bitorder="little").astype(np.int16)
        signs = unpacked * 2 - 1
        return signs @ query_q4.astype(np.int16)

    def search(self, query_vector: np.ndarray, top_k: int, *, candidate_ids: Sequence[int] | None = None, oversample: int | None = None) -> list[VectorHit]:
        if top_k <= 0 or self.row_count <= 0:
            return []
        query = normalize_embeddings(np.asarray(query_vector, dtype=np.float32).reshape(1, -1))[0]
        if query.shape[0] != self.dimensions:
            raise ValueError("query embedding dimension mismatch")
        query_scale = max(float(np.max(np.abs(query))), 1e-12)
        query_q4 = np.clip(np.rint(query / query_scale * 7.0), -7, 7).astype(np.int8)
        active_oversample = max(1, int(oversample or self.oversample))
        coarse_keep = max(top_k, top_k * active_oversample)
        candidate_chunks: list[np.ndarray] = []
        score_chunks: list[np.ndarray] = []
        ids_array = np.asarray(candidate_ids, dtype=np.int64) if candidate_ids is not None else None
        total = len(ids_array) if ids_array is not None else self.row_count
        for start in range(0, total, self.block_rows):
            if ids_array is None:
                block_ids = np.arange(start, min(total, start + self.block_rows), dtype=np.int64)
            else:
                block_ids = ids_array[start : start + self.block_rows]
            if block_ids.size == 0:
                continue
            block_scores = self._coarse_scores(block_ids, query_q4)
            keep = min(coarse_keep, block_ids.size)
            local = np.argpartition(block_scores, -keep)[-keep:] if keep < block_ids.size else np.arange(block_ids.size)
            candidate_chunks.append(block_ids[local]); score_chunks.append(block_scores[local])
        if not candidate_chunks:
            return []
        coarse_ids = np.concatenate(candidate_chunks); coarse_scores = np.concatenate(score_chunks)
        keep = min(coarse_keep, coarse_ids.size)
        if keep < coarse_ids.size:
            selection = np.argpartition(coarse_scores, -keep)[-keep:]
            coarse_ids = coarse_ids[selection]
        target_vectors = np.asarray(self._int8[coarse_ids], dtype=np.float32) / 127.0
        rerank_scores = target_vectors @ query
        order = np.argsort(rerank_scores)[::-1][: min(top_k, rerank_scores.size)]
        return [VectorHit(row_id=int(coarse_ids[index]), score=float(rerank_scores[index])) for index in order]

    def record(self, row_id: int) -> dict[str, object]:
        if row_id < 0 or row_id >= self.row_count:
            raise IndexError(row_id)
        offset = int(self._offsets[row_id])
        with (self.root / self.RECORDS_FILE).open("rb") as stream:
            stream.seek(offset); line = stream.readline()
        return json.loads(line.decode("utf-8"))

    def records(self, row_ids: Sequence[int]) -> dict[int, dict[str, object]]:
        return {row_id: self.record(row_id) for row_id in row_ids}

    def candidate_ids_for_scope(self, source_row: Mapping[str, object], config: MatchingConfig) -> list[int] | None:
        if config.scope_mode == "GLOBAL":
            return None
        source_field = config.scope.source_field
        if not source_field:
            return []
        source_value = source_row.get(source_field)
        if source_value is None:
            return []
        if config.scope_mode == "STRICT":
            target_values = [str(source_value)]
        else:
            target_values = [str(value) for value in config.scope.mapping.get(str(source_value), [])]
        merged: list[int] = []
        for value in target_values:
            merged.extend(self._postings.get(value, []))
        return merged
