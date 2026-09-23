from __future__ import annotations

from dataclasses import dataclass
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

# Portable popcount table. The target vectors remain packed throughout the coarse
# scan; this avoids expanding an N x dimensions sign matrix for every query.
_POPCOUNT_LUT = np.unpackbits(np.arange(256, dtype=np.uint8)[:, None], axis=1).sum(axis=1).astype(np.uint8)
_BYTE_VALUES = np.arange(256, dtype=np.uint8)
_BYTE_BITS = np.unpackbits(_BYTE_VALUES[:, None], axis=1, bitorder="little").astype(np.int16)


def _build_query_score_table(query_q4: np.ndarray, packed_dimensions: int) -> np.ndarray:
    """Per byte position x byte value XNOR-weight table, mathematically equal to
    sum_k 2^k * popcount(sign_diff & plane_k) up to the positive affine transform
    (old = 2 * new - total_weight), so candidate ordering is preserved exactly.
    """
    weights = np.abs(np.asarray(query_q4, dtype=np.int8)).astype(np.int16)
    sign_bits = np.unpackbits(np.packbits(np.asarray(query_q4) >= 0, bitorder="little"), bitorder="little").astype(np.int16)
    padded_length = packed_dimensions * 8
    if weights.shape[0] < padded_length:
        weights = np.pad(weights, (0, padded_length - weights.shape[0]))
    sign_groups = sign_bits[: padded_length].reshape(packed_dimensions, 8)
    weight_groups = weights[: padded_length].reshape(packed_dimensions, 8)
    xnor = 1 - (_BYTE_BITS[:, None, :] ^ sign_groups[None, :, :])
    table = (xnor * weight_groups[None, :, :]).sum(axis=2, dtype=np.int16)
    return np.ascontiguousarray(table.T).ravel()


def _coarse_scores_table(target_packed: np.ndarray, table: np.ndarray) -> np.ndarray:
    packed = np.asarray(target_packed, dtype=np.uint8)
    if packed.ndim != 2:
        raise ValueError("target packed bits must be a 2D array")
    positions = packed.shape[1]
    index = packed.astype(np.uint16) | (np.arange(positions, dtype=np.uint16) << np.uint16(8))
    return table[index].sum(axis=1, dtype=np.int32)


_SCAN_WORKER: dict[str, object] = {}


def _init_scan_worker(root_str: str, dimensions: int, packed_dimensions: int, row_count: int, block_rows: int) -> None:
    from pathlib import Path as _Path

    root = _Path(root_str)
    _SCAN_WORKER["bits"] = np.memmap(root / EmbeddedBBQFlatIndex.BITS_FILE, dtype=np.uint8, mode="r", shape=(row_count, packed_dimensions))
    _SCAN_WORKER["dimensions"] = dimensions
    _SCAN_WORKER["packed_dimensions"] = packed_dimensions
    _SCAN_WORKER["row_count"] = row_count
    _SCAN_WORKER["block_rows"] = block_rows


def _scan_shard(payload: tuple[int, int, int, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Return per-query partial top-k (ids int64, scores int32) for one row shard."""
    start_row, stop_row, keep, queries = payload
    bits = _SCAN_WORKER["bits"]
    packed_dimensions = int(_SCAN_WORKER["packed_dimensions"])
    block_rows = int(_SCAN_WORKER["block_rows"])
    query_count = int(queries.shape[0])
    ids_out = np.full((query_count, keep), -1, dtype=np.int64)
    scores_out = np.full((query_count, keep), np.iinfo(np.int32).min, dtype=np.int32)
    for q_index in range(query_count):
        query = np.asarray(queries[q_index], dtype=np.float32)
        norm = float(np.linalg.norm(query))
        if norm <= 0:
            continue
        normalized = query / norm
        scale = max(float(np.max(np.abs(normalized))), 1e-12)
        query_q4 = np.clip(np.rint(normalized / scale * 7.0), -7, 7).astype(np.int8)
        table = _build_query_score_table(query_q4, packed_dimensions)
        collected_ids: list[np.ndarray] = []
        collected_scores: list[np.ndarray] = []
        for block_start in range(start_row, stop_row, block_rows):
            block_stop = min(stop_row, block_start + block_rows)
            packed = np.asarray(bits[block_start:block_stop])
            block_scores = _coarse_scores_table(packed, table)
            local_keep = min(keep, block_scores.shape[0])
            local = np.argpartition(block_scores, -local_keep)[-local_keep:] if local_keep < block_scores.shape[0] else np.arange(block_scores.shape[0])
            collected_ids.append(block_start + local.astype(np.int64))
            collected_scores.append(block_scores[local])
        if not collected_ids:
            continue
        ids = np.concatenate(collected_ids)
        scores = np.concatenate(collected_scores)
        top = min(keep, ids.shape[0])
        selection = _stable_top(scores, ids, top)
        ids_out[q_index, :top] = ids[selection]
        scores_out[q_index, :top] = scores[selection]
    return ids_out, scores_out


def _stable_top(scores: np.ndarray, ids: np.ndarray, top: int) -> np.ndarray:
    """Deterministic top-`top` by (score desc, row id asc) so sharded and sequential
    scans return byte-identical candidate sets."""
    order = np.lexsort((ids, -scores.astype(np.int64)))
    return order[:top]


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
    """1-bit Target + signed 4-bit Query coarse search with int8 rerank.

    Target signs are persisted as one packed bit per dimension. Query values are
    normalized and quantized to signed magnitude [-7, 7] (one sign bit + three
    magnitude bit-planes). The coarse dot product is evaluated directly against
    packed Target bytes with XOR/AND + a uint8 popcount LUT. No Target `unpackbits`
    or Source x Target matrix is created in the query hot path.
    """

    METADATA_FILE = "metadata.json"
    BITS_FILE = "target.bbq.u8"
    INT8_FILE = "target.rerank.i8"
    RECORDS_FILE = "records.jsonl"
    OFFSETS_FILE = "records.offsets.u64"
    POSTINGS_FILE = "scope.postings.json"
    LSH_KEYS_FILE = "ann.lsh.keys.u32"
    LSH_IDS_FILE = "ann.lsh.ids.u32"
    LSH_SEED = 16220260923
    COARSE_KERNEL = "packed_weighted_byte_lut_q4_v2"

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
        ann = self.metadata.get("ann", {})
        ann = ann if isinstance(ann, dict) else {}
        self.ann_enabled = bool(ann.get("enabled")) and (root / self.LSH_KEYS_FILE).exists() and (root / self.LSH_IDS_FILE).exists()
        self.ann_tables = int(ann.get("tables", 0) or 0)
        self.ann_bits = int(ann.get("bits", 0) or 0)
        self.ann_probe_radius = int(ann.get("probe_radius", 0) or 0)
        self.ann_candidate_limit = int(ann.get("candidate_limit", 0) or 0)
        positions = ann.get("positions", [])
        self._lsh_positions = np.asarray(positions, dtype=np.int32) if positions else np.empty((0, 0), dtype=np.int32)
        if self.ann_enabled:
            self._lsh_keys = np.memmap(root / self.LSH_KEYS_FILE, dtype="<u4", mode="r", shape=(self.ann_tables, self.row_count))
            self._lsh_ids = np.memmap(root / self.LSH_IDS_FILE, dtype="<u4", mode="r", shape=(self.ann_tables, self.row_count))
        else:
            self._lsh_keys = None
            self._lsh_ids = None
        self._scan_pool = None
        self._scan_pool_workers = 0

    @staticmethod
    def _lsh_positions_for(dimensions: int, tables: int, bits: int) -> np.ndarray:
        """Deterministic random hyperplane coordinates used by sign-LSH.

        Coordinates are sampled without replacement per table. The index stores
        only sorted uint32 bucket keys + row ids, so a million-row index remains
        bounded and mmap-friendly instead of copying target vectors per worker.
        """
        active_bits = max(1, min(int(bits), int(dimensions), 24))
        active_tables = max(1, int(tables))
        rng = np.random.default_rng(EmbeddedBBQFlatIndex.LSH_SEED + int(dimensions))
        return np.stack(
            [rng.choice(dimensions, size=active_bits, replace=False) for _ in range(active_tables)],
            axis=0,
        ).astype(np.int32, copy=False)

    @staticmethod
    def _lsh_codes_from_packed(packed: np.ndarray, positions: np.ndarray) -> np.ndarray:
        packed = np.asarray(packed, dtype=np.uint8)
        codes = np.zeros(packed.shape[0], dtype=np.uint32)
        for output_bit, dimension in enumerate(np.asarray(positions, dtype=np.int32)):
            dim = int(dimension)
            byte_index = dim // 8
            mask = np.uint8(1 << (dim % 8))
            bit = ((packed[:, byte_index] & mask) != 0).astype(np.uint32)
            codes |= bit << np.uint32(output_bit)
        return codes

    def _ann_candidate_ids(
        self,
        query_vector: np.ndarray,
        coarse_keep: int,
        stats: dict[str, int | bool] | None = None,
    ) -> np.ndarray | None:
        """Return a bounded ANN candidate set, or None for exact-scan fallback.

        Pathological low-entropy buckets may contain a large fraction of the
        index. In that case we intentionally fall back to the existing mmap
        block scan before materializing the bucket union. This preserves recall
        and keeps temporary Python/Numpy allocations bounded.
        """
        if not self.ann_enabled or self._lsh_keys is None or self._lsh_ids is None:
            return None
        hard_limit = max(int(coarse_keep), int(self.ann_candidate_limit))
        occurrence_limit = max(hard_limit * 8, hard_limit + 1024)
        query, query_q4 = self._quantized(query_vector)
        query_sign = np.packbits(query >= 0.0, bitorder="little")
        gathered: list[np.ndarray] = []
        raw_occurrences = 0
        for table_index in range(self.ann_tables):
            positions = self._lsh_positions[table_index]
            code = 0
            for output_bit, dimension in enumerate(positions):
                dim = int(dimension)
                if query_sign[dim // 8] & np.uint8(1 << (dim % 8)):
                    code |= 1 << output_bit
            probes = [code]
            if self.ann_probe_radius >= 1:
                probes.extend(code ^ (1 << bit) for bit in range(self.ann_bits))
            keys = self._lsh_keys[table_index]
            ids = self._lsh_ids[table_index]
            probe_array = np.asarray(probes, dtype=np.uint32)
            lefts = np.searchsorted(keys, probe_array, side="left")
            rights = np.searchsorted(keys, probe_array, side="right")
            raw_occurrences += int(np.sum(rights - lefts, dtype=np.int64))
            if raw_occurrences > occurrence_limit:
                if stats is not None:
                    stats.update({
                        "ann_fallback": True,
                        "ann_raw_occurrences": raw_occurrences,
                        "candidate_pool_count": self.row_count,
                    })
                return None
            table_parts = [ids[left:right] for left, right in zip(lefts.tolist(), rights.tolist()) if right > left]
            if table_parts:
                gathered.append(np.concatenate(table_parts))
        if not gathered:
            if stats is not None:
                stats.update({
                    "ann_fallback": True,
                    "ann_raw_occurrences": 0,
                    "candidate_pool_count": self.row_count,
                })
            return None
        candidate_ids = np.unique(np.concatenate(gathered)).astype(np.int64, copy=False)
        if candidate_ids.size > hard_limit:
            scores = self._coarse_scores(candidate_ids, query_q4)
            selection = _stable_top(scores, candidate_ids, hard_limit)
            candidate_ids = candidate_ids[selection]
        if stats is not None:
            stats.update({
                "ann_fallback": False,
                "ann_raw_occurrences": raw_occurrences,
                "candidate_pool_count": int(candidate_ids.size),
            })
        return candidate_ids

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
        ann_min_rows: int = 100_000,
        ann_lsh_tables: int = 48,
        ann_lsh_bits: int = 16,
        ann_probe_radius: int = 1,
        ann_candidate_limit: int = 12_000,
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
        lsh_keys_path = temporary / cls.LSH_KEYS_FILE
        lsh_ids_path = temporary / cls.LSH_IDS_FILE
        target_signature = retrieval_text_signature(config, "target")
        postings: dict[str, list[int]] = {}
        scope_field = config.scope.target_field if config.scope_mode != "GLOBAL" else None
        row_count = 0
        cache_hits = 0
        cache_misses = 0

        def flush_batch(batch: list[dict[str, object]], bits_stream, int8_stream, records_stream, offsets_stream) -> None:
            nonlocal row_count, cache_hits, cache_misses
            if not batch:
                return
            texts = [build_retrieval_text(row, config, "target") for row in batch]
            vectors, stats = cache.get_or_embed(texts, target_signature, embedding_batch_size)
            cache_hits += stats.hits
            cache_misses += stats.misses
            vectors = normalize_embeddings(vectors)
            if len(vectors) >= 8 and float(np.max(np.std(vectors, axis=0))) < 1e-8:
                raise DomainError(
                    "EMBEDDING_DEGENERATE",
                    "向量编码退化（所有文本得到相同向量），索引已拒绝缓存。请确认 Embedding 模型已就绪后重试；本次匹配将按可用通道降级计分。",
                    status_code=503,
                )
            np.packbits(vectors >= 0.0, axis=1, bitorder="little").tofile(bits_stream)
            np.clip(np.rint(vectors * 127.0), -127, 127).astype(np.int8).tofile(int8_stream)
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
                    if build_retrieval_text(row, config, "target") == "":
                        continue
                    batch.append(row)
                    if len(batch) >= embedding_batch_size:
                        flush_batch(batch, bits_stream, int8_stream, records_stream, offsets_stream)
                        batch = []
                flush_batch(batch, bits_stream, int8_stream, records_stream, offsets_stream)
            if row_count == 0:
                raise DomainError("INDEX_EMPTY", "集团目录没有可用于向量索引的有效记录", status_code=422)
            (temporary / cls.POSTINGS_FILE).write_text(json.dumps(postings, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

            ann_metadata: dict[str, object] = {"enabled": False}
            if row_count >= max(1, int(ann_min_rows)):
                tables = max(1, int(ann_lsh_tables))
                bits = max(4, min(24, int(ann_lsh_bits), provider.spec.dimensions))
                positions = cls._lsh_positions_for(provider.spec.dimensions, tables, bits)
                packed_dimensions = (provider.spec.dimensions + 7) // 8
                packed = np.memmap(bits_path, dtype=np.uint8, mode="r", shape=(row_count, packed_dimensions))
                keys_map = np.memmap(lsh_keys_path, dtype="<u4", mode="w+", shape=(tables, row_count))
                ids_map = np.memmap(lsh_ids_path, dtype="<u4", mode="w+", shape=(tables, row_count))
                base_ids = np.arange(row_count, dtype=np.uint32)
                for table_index in range(tables):
                    codes = cls._lsh_codes_from_packed(packed, positions[table_index])
                    order = np.argsort(codes, kind="stable")
                    keys_map[table_index] = codes[order]
                    ids_map[table_index] = base_ids[order]
                keys_map.flush()
                ids_map.flush()
                del keys_map, ids_map, packed
                ann_metadata = {
                    "enabled": True,
                    "backend": "multi_table_sign_lsh_v1",
                    "tables": tables,
                    "bits": bits,
                    "probe_radius": max(0, min(1, int(ann_probe_radius))),
                    "candidate_limit": max(128, int(ann_candidate_limit)),
                    "positions": positions.tolist(),
                }
            full_metadata = {
                **metadata,
                "format_version": 3,
                "algorithm": "embedded_bbq_lsh",
                "coarse_kernel": cls.COARSE_KERNEL,
                "row_count": row_count,
                "dimensions": provider.spec.dimensions,
                "target_bits": 1,
                "query_bits": 4,
                "rerank": "int8",
                "scan_block_rows": scan_block_rows,
                "oversample": config.retrieval.oversample,
                "target_text_signature": target_signature,
                "scope_target_field": scope_field,
                "ann": ann_metadata,
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

    @staticmethod
    def quantize_query(query_vector: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        query = normalize_embeddings(np.asarray(query_vector, dtype=np.float32).reshape(1, -1))[0]
        scale = max(float(np.max(np.abs(query))), 1e-12)
        query_q4 = np.clip(np.rint(query / scale * 7.0), -7, 7).astype(np.int8)
        return query, query_q4

    @staticmethod
    def _pack_query(query_q4: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        values = np.asarray(query_q4, dtype=np.int8)
        magnitude = np.abs(values).astype(np.uint8)
        sign_packed = np.packbits(values >= 0, bitorder="little")
        planes = np.stack(
            [np.packbits(((magnitude >> bit) & 1).astype(np.uint8), bitorder="little") for bit in range(3)],
            axis=0,
        )
        active_counts = np.asarray([int(_POPCOUNT_LUT[plane].sum(dtype=np.int64)) for plane in planes], dtype=np.int32)
        return sign_packed, planes, active_counts

    @staticmethod
    def _coarse_scores_packed(
        target_packed: np.ndarray,
        sign_packed: np.ndarray,
        magnitude_planes: np.ndarray,
        active_counts: np.ndarray,
    ) -> np.ndarray:
        packed = np.asarray(target_packed, dtype=np.uint8)
        if packed.ndim != 2:
            raise ValueError("target packed bits must be a 2D array")
        sign_diff = np.bitwise_xor(packed, sign_packed)
        scores = np.zeros(packed.shape[0], dtype=np.int32)
        for bit in range(3):
            plane = magnitude_planes[bit]
            mismatches = _POPCOUNT_LUT[np.bitwise_and(sign_diff, plane)].sum(axis=1, dtype=np.int32)
            scores += (int(active_counts[bit]) - (mismatches << 1)) * (1 << bit)
        return scores

    def _coarse_scores(self, row_ids: np.ndarray, query_q4: np.ndarray) -> np.ndarray:
        table = _build_query_score_table(query_q4, self.packed_dimensions)
        packed = np.asarray(self._bits[row_ids])
        return _coarse_scores_table(packed, table)

    def _quantized(self, query_vector: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return self.quantize_query(query_vector)

    def search(
        self,
        query_vector: np.ndarray,
        top_k: int,
        *,
        candidate_ids: Sequence[int] | None = None,
        oversample: int | None = None,
        stats: dict[str, int | bool] | None = None,
    ) -> list[VectorHit]:
        if top_k <= 0 or self.row_count <= 0:
            return []
        query, query_q4 = self._quantized(query_vector)
        if query.shape[0] != self.dimensions:
            raise ValueError("query embedding dimension mismatch")
        table = _build_query_score_table(query_q4, self.packed_dimensions)
        active_oversample = max(1, int(oversample or self.oversample))
        coarse_keep = max(top_k, top_k * active_oversample)
        candidate_chunks: list[np.ndarray] = []
        score_chunks: list[np.ndarray] = []
        if candidate_ids is not None:
            ids_array = np.asarray(candidate_ids, dtype=np.int64)
            if stats is not None:
                stats.update({"ann_fallback": False, "candidate_pool_count": int(ids_array.size)})
        elif self.ann_enabled:
            ids_array = self._ann_candidate_ids(query, coarse_keep, stats=stats)
        else:
            ids_array = None
            if stats is not None:
                stats.update({"ann_fallback": False, "candidate_pool_count": self.row_count})
        total = len(ids_array) if ids_array is not None else self.row_count
        for start in range(0, total, self.block_rows):
            if ids_array is None:
                stop = min(total, start + self.block_rows)
                block_ids = np.arange(start, stop, dtype=np.int64)
                # Sequential mmap slice avoids a fancy-index copy on global scans.
                packed = np.asarray(self._bits[start:stop])
            else:
                block_ids = ids_array[start : start + self.block_rows]
                packed = np.asarray(self._bits[block_ids])
            if block_ids.size == 0:
                continue
            block_scores = _coarse_scores_table(packed, table)
            keep = min(coarse_keep, block_ids.size)
            local = np.argpartition(block_scores, -keep)[-keep:] if keep < block_ids.size else np.arange(block_scores.size)
            candidate_chunks.append(block_ids[local])
            score_chunks.append(block_scores[local])
        if not candidate_chunks:
            return []
        coarse_ids = np.concatenate(candidate_chunks)
        coarse_scores = np.concatenate(score_chunks)
        keep = min(coarse_keep, coarse_ids.size)
        if keep < coarse_ids.size:
            coarse_ids = coarse_ids[_stable_top(coarse_scores, coarse_ids, keep)]
        target_vectors = np.asarray(self._int8[coarse_ids], dtype=np.float32) / 127.0
        rerank_scores = target_vectors @ query
        order = np.argsort(rerank_scores)[::-1][: min(top_k, rerank_scores.size)]
        result = [VectorHit(row_id=int(coarse_ids[index]), score=float(rerank_scores[index])) for index in order]
        if stats is not None:
            stats["rerank_count"] = int(coarse_ids.size)
            stats["returned_count"] = len(result)
        return result

    def close(self) -> None:
        pool = getattr(self, "_scan_pool", None)
        if pool is not None:
            self._scan_pool = None
            pool.shutdown(wait=False)

    def search_many(
        self,
        queries: np.ndarray,
        top_k: int,
        *,
        oversample: int | None = None,
        scan_workers: int = 0,
        stats_out: list[dict[str, int | bool]] | None = None,
    ) -> list[list[VectorHit]]:
        """Batched global search. Uses a forked process pool over row shards when
        scan_workers > 1; results are equivalent to repeated search() calls."""
        matrix = np.asarray(queries, dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[1] != self.dimensions:
            raise ValueError("query matrix dimension mismatch")
        workers = max(0, int(scan_workers))
        if self.row_count <= 0 or top_k <= 0 or matrix.shape[0] == 0:
            return [[] for _ in range(matrix.shape[0])]
        if self.ann_enabled:
            def run_one(index: int) -> tuple[list[VectorHit], dict[str, int | bool]]:
                local_stats: dict[str, int | bool] = {}
                hits = self.search(matrix[index], top_k, oversample=oversample, stats=local_stats)
                return hits, local_stats

            if workers <= 1:
                pairs = [run_one(index) for index in range(matrix.shape[0])]
            else:
                from concurrent.futures import ThreadPoolExecutor
                active_workers = min(workers, matrix.shape[0])
                with ThreadPoolExecutor(max_workers=active_workers, thread_name_prefix="matcher-ann") as pool:
                    futures = [pool.submit(run_one, index) for index in range(matrix.shape[0])]
                    pairs = [future.result() for future in futures]
            if stats_out is not None:
                stats_out.extend(item[1] for item in pairs)
            return [item[0] for item in pairs]
        if workers <= 1:
            results: list[list[VectorHit]] = []
            for index in range(matrix.shape[0]):
                local_stats: dict[str, int | bool] = {}
                results.append(self.search(matrix[index], top_k, oversample=oversample, stats=local_stats))
                if stats_out is not None:
                    stats_out.append(local_stats)
            return results
        active_oversample = max(1, int(oversample or self.oversample))
        coarse_keep = max(top_k, top_k * active_oversample)
        workers = min(workers, max(1, matrix.shape[0]), self.row_count // max(self.block_rows, 1) or 1)
        shard_blocks = max(1, (self.row_count + self.block_rows - 1) // self.block_rows)
        bounds: list[tuple[int, int]] = []
        for shard in range(workers):
            first_block = shard * shard_blocks // workers
            last_block = (shard + 1) * shard_blocks // workers
            start = min(first_block * self.block_rows, self.row_count)
            stop = min(last_block * self.block_rows, self.row_count)
            if stop > start:
                bounds.append((start, stop))
        pool = getattr(self, "_scan_pool", None)
        if pool is None or self._scan_pool_workers < len(bounds):
            if pool is not None:
                pool.shutdown(wait=False)
            from concurrent.futures import ProcessPoolExecutor

            pool = ProcessPoolExecutor(
                max_workers=len(bounds),
                initializer=_init_scan_worker,
                initargs=(str(self.root), self.dimensions, self.packed_dimensions, self.row_count, self.block_rows),
            )
            self._scan_pool = pool
            self._scan_pool_workers = len(bounds)
        futures = [pool.submit(_scan_shard, (start, stop, coarse_keep, matrix)) for start, stop in bounds]
        shards = [future.result() for future in futures]
        results: list[list[VectorHit]] = []
        for q_index in range(matrix.shape[0]):
            ids = np.concatenate([shard_ids[q_index] for shard_ids, _ in shards])
            scores = np.concatenate([shard_scores[q_index] for _, shard_scores in shards])
            valid = ids >= 0
            ids = ids[valid]
            scores = scores[valid]
            if ids.size == 0:
                results.append([])
                continue
            keep = min(coarse_keep, ids.size)
            if ids.size > keep:
                ids = ids[_stable_top(scores, ids, keep)]
            query = matrix[q_index]
            norm = float(np.linalg.norm(query))
            if norm <= 0:
                results.append([])
                continue
            query = query / norm
            target_vectors = np.asarray(self._int8[ids], dtype=np.float32) / 127.0
            rerank_scores = target_vectors @ query
            order = np.argsort(rerank_scores)[::-1][: min(top_k, rerank_scores.size)]
            result = [VectorHit(row_id=int(ids[index]), score=float(rerank_scores[index])) for index in order]
            results.append(result)
            if stats_out is not None:
                stats_out.append({
                    "ann_fallback": False,
                    "candidate_pool_count": self.row_count,
                    "rerank_count": int(ids.size),
                    "returned_count": len(result),
                })
        return results

    def record(self, row_id: int) -> dict[str, object]:
        if row_id < 0 or row_id >= self.row_count:
            raise IndexError(row_id)
        offset = int(self._offsets[row_id])
        with (self.root / self.RECORDS_FILE).open("rb") as stream:
            stream.seek(offset)
            line = stream.readline()
        return json.loads(line.decode("utf-8"))

    def records(self, row_ids: Sequence[int]) -> dict[int, dict[str, object]]:
        unique = sorted(set(int(row_id) for row_id in row_ids))
        if not unique:
            return {}
        result: dict[int, dict[str, object]] = {}
        with (self.root / self.RECORDS_FILE).open("rb") as stream:
            for row_id in unique:
                stream.seek(int(self._offsets[row_id]))
                result[row_id] = json.loads(stream.readline().decode("utf-8"))
        return result

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
