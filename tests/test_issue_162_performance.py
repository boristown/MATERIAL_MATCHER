from __future__ import annotations

from pathlib import Path
import threading
import time

import numpy as np

from material_matcher.domain.models import MatchingConfig
from material_matcher.embedding.cache import EmbeddingCache
from material_matcher.embedding.providers import DeterministicEmbeddingProvider
from material_matcher.matching.engine import CandidateResult, RowResult, match_rows_indexed
from material_matcher.services.match_service import MatchService
from material_matcher.settings import Settings
from material_matcher.storage.files import FileRepository
from material_matcher.storage.metadata import MetadataRepository
from material_matcher.vector.index import EmbeddedBBQFlatIndex


def _config(dimensions: int = 32, *, top_k: int = 12, top_n: int = 5) -> MatchingConfig:
    return MatchingConfig.model_validate({
        "source_id_column": "物料号",
        "scope_mode": "GLOBAL",
        "rules": [
            {
                "id": "semantic-name",
                "source": {"fields": ["文本"]},
                "target": {"fields": ["文本"]},
                "matcher": "semantic",
                "weight": 70,
            },
            {
                "id": "model",
                "source": {"fields": ["型号"]},
                "target": {"fields": ["型号"]},
                "matcher": "exact",
                "weight": 30,
            },
        ],
        "retrieval": {
            "mode": "vector",
            "provider": "deterministic_test",
            "model_id": "deterministic-test-v1",
            "dimensions": dimensions,
            "source": {"fields": ["文本"]},
            "target": {"fields": ["文本"]},
            "retrieval_top_k": top_k,
            "oversample": 3,
        },
        "decision": {
            "success_threshold": 50,
            "review_enabled": True,
            "top_n": top_n,
        },
    })


def _build_ann_index(tmp_path: Path, *, rows: int = 3000, dimensions: int = 32) -> tuple[EmbeddedBBQFlatIndex, DeterministicEmbeddingProvider, MatchingConfig]:
    provider = DeterministicEmbeddingProvider(dimensions)
    config = _config(dimensions)
    cache = EmbeddingCache(tmp_path / "cache", provider)
    target_rows = (
        {
            "集团码": f"G{index:06d}",
            "文本": f"工业物料 {index:06d} 高可靠元件 型号 M{index % 257:03d}",
            "型号": f"M{index % 257:03d}",
        }
        for index in range(rows)
    )
    index, _ = EmbeddedBBQFlatIndex.build(
        tmp_path / "index",
        provider=provider,
        cache=cache,
        target_rows=target_rows,
        config=config,
        group_code_column="集团码",
        metadata={"test": "issue-162"},
        embedding_batch_size=128,
        scan_block_rows=256,
        ann_min_rows=100,
        ann_lsh_tables=48,
        ann_lsh_bits=12,
        ann_probe_radius=1,
        ann_candidate_limit=512,
    )
    assert index.ann_enabled is True
    return index, provider, config


def test_large_index_ann_candidate_set_is_bounded_and_keeps_exact_top1(tmp_path: Path) -> None:
    index, provider, _ = _build_ann_index(tmp_path)
    text = "工业物料 001337 高可靠元件 型号 M052"
    query = provider.embed([text])[0]

    index.ann_enabled = False
    exact = index.search(query, 5, oversample=3)
    index.ann_enabled = True
    bounded = index.search(query, 5, oversample=3)

    candidates = index._ann_candidate_ids(query, coarse_keep=15)
    assert candidates is not None
    assert candidates.size <= 512
    assert exact[0].row_id == 1337
    assert bounded[0].row_id == exact[0].row_id
    assert [hit.row_id for hit in bounded][:1] == [hit.row_id for hit in exact][:1]


def test_ann_search_many_parallelizes_source_queries_without_copying_index(tmp_path: Path) -> None:
    index, provider, _ = _build_ann_index(tmp_path, rows=1200)
    queries = provider.embed([
        f"工业物料 {index_no:06d} 高可靠元件 型号 M{index_no % 257:03d}"
        for index_no in range(16)
    ])
    thread_ids: set[int] = set()
    lock = threading.Lock()
    original = index.search

    def observed_search(*args, **kwargs):
        with lock:
            thread_ids.add(threading.get_ident())
        time.sleep(0.005)
        return original(*args, **kwargs)

    index.search = observed_search  # type: ignore[method-assign]
    try:
        results = index.search_many(queries, 8, oversample=3, scan_workers=4)
    finally:
        index.search = original  # type: ignore[method-assign]
    assert len(results) == 16
    assert len(thread_ids) > 1
    assert all(len(items) <= 8 for items in results)


def test_indexed_matching_streams_bounded_batches_and_candidates(tmp_path: Path) -> None:
    index, provider, config = _build_ann_index(tmp_path, rows=1500)
    source = tmp_path / "source.csv"
    lines = ["物料号,文本,型号"]
    for row in range(20):
        target = row * 7
        lines.append(
            f"S{row:04d},工业物料 {target:06d} 高可靠元件 型号 M{target % 257:03d},M{target % 257:03d}"
        )
    source.write_text("\n".join(lines) + "\n", encoding="utf-8")

    cache = EmbeddingCache(tmp_path / "cache", provider)
    batches: list[list[RowResult]] = []
    metrics: dict[str, object] = {}
    rows = match_rows_indexed(
        source,
        index=index,
        provider=provider,
        cache=cache,
        config=config,
        group_code_column="集团码",
        query_batch_size=8,
        match_workers=3,
        on_batch=lambda batch: batches.append(batch),
        batch_rows=5,
        collect_results=False,
        performance_metrics=metrics,
    )

    assert rows == []
    assert sum(len(batch) for batch in batches) == 20
    assert all(1 <= len(batch) <= 5 for batch in batches)
    assert metrics["worker_count"] == 3
    candidate_counts = metrics["_candidate_counts"]
    candidate_pool_counts = metrics["_candidate_pool_counts"]
    rerank_counts = metrics["_rerank_counts"]
    assert isinstance(candidate_counts, list)
    assert isinstance(candidate_pool_counts, list)
    assert isinstance(rerank_counts, list)
    assert len(candidate_counts) == len(candidate_pool_counts) == len(rerank_counts) == 20
    assert max(candidate_counts) <= config.retrieval.retrieval_top_k
    assert all(pool >= returned for pool, returned in zip(candidate_pool_counts, candidate_counts))
    assert all(rerank >= returned for rerank, returned in zip(rerank_counts, candidate_counts))
    timings = metrics["timings"]
    assert isinstance(timings, dict)
    for phase in ("parsing", "normalization", "source preprocessing", "retrieval", "rerank/scoring", "decision"):
        assert phase in timings



def test_pathological_ann_bucket_falls_back_to_exact_scan_without_quality_loss(tmp_path: Path) -> None:
    index, provider, _ = _build_ann_index(tmp_path, rows=1600)
    query = provider.embed(["工业物料 000777 高可靠元件 型号 M006"])[0]

    index.ann_enabled = False
    exact = index.search(query, 5, oversample=3)
    index.ann_enabled = True

    # Force every probed table bucket to contain the whole index. The ANN
    # implementation must detect this before materializing the union and use
    # the original mmap exact-scan path instead of dropping candidates.
    query_norm, _ = index._quantized(query)
    query_sign = np.packbits(query_norm >= 0.0, bitorder="little")
    keys = np.empty((index.ann_tables, index.row_count), dtype=np.uint32)
    ids = np.tile(np.arange(index.row_count, dtype=np.uint32), (index.ann_tables, 1))
    for table_index, positions in enumerate(index._lsh_positions):
        code = 0
        for output_bit, dimension in enumerate(positions):
            dim = int(dimension)
            if query_sign[dim // 8] & np.uint8(1 << (dim % 8)):
                code |= 1 << output_bit
        keys[table_index].fill(np.uint32(code))
    index._lsh_keys = keys
    index._lsh_ids = ids
    index.ann_candidate_limit = 16

    stats: dict[str, int | bool] = {}
    fallback = index._ann_candidate_ids(query, coarse_keep=15, stats=stats)
    bounded = index.search(query, 5, oversample=3, stats=stats)

    assert fallback is None
    assert stats["ann_fallback"] is True
    assert stats["candidate_pool_count"] == index.row_count
    assert [hit.row_id for hit in bounded] == [hit.row_id for hit in exact]

def test_match_service_batch_persistence_keeps_topn_and_traceability(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "etc",
        log_dir=tmp_path / "log",
        admin_password="x",
    )
    settings.ensure_dirs()
    metadata = MetadataRepository(settings.metadata_db_path)
    files = FileRepository(settings.data_dir, metadata)
    service = MatchService(metadata, files, settings)

    rows: list[RowResult] = []
    for source_index in range(3):
        candidates = [
            CandidateResult(
                rank=rank,
                group_code=f"G{source_index}{rank}",
                score=90.0 - rank,
                raw_score=0.9,
                critical_conflict=False,
                target_payload={"集团码": f"G{source_index}{rank}", "名称": "测试"},
                field_scores=[{"rule_id": "r1", "score": 1.0}],
                target_row_number=100 + rank,
            )
            for rank in range(1, 6)
        ]
        rows.append(
            RowResult(
                source_row_id=str(source_index + 1),
                source_id=f"S{source_index + 1}",
                source_payload={"物料号": f"S{source_index + 1}"},
                status="MATCHED",
                final_group_code=candidates[0].group_code,
                first_score=candidates[0].score,
                second_score=candidates[1].score,
                score_gap=1.0,
                critical_conflict=False,
                candidates=candidates,
                source_row_number=source_index + 2,
            )
        )

    with metadata.connect() as connection:
        connection.execute(
            """INSERT INTO tasks(task_id,name,source_file_id,catalog_version_id,config_snapshot,config_sha256,
               stage,status,progress,processed_rows,total_rows,created_at)
               VALUES('t-perf','perf','source','catalog','{}','x','MATCH','RUNNING',0,0,0,'now')"""
        )
    service._persist_rows("t-perf", rows)
    with metadata.connect() as connection:
        item_count = connection.execute("SELECT COUNT(*) FROM match_items WHERE task_id='t-perf'").fetchone()[0]
        candidate_count = connection.execute("SELECT COUNT(*) FROM match_candidates WHERE task_id='t-perf'").fetchone()[0]
        row_number = connection.execute(
            "SELECT target_row_number FROM match_candidates WHERE task_id='t-perf' AND source_row_id='1' AND rank=1"
        ).fetchone()[0]
    assert item_count == 3
    assert candidate_count == 15
    assert row_number == 101
