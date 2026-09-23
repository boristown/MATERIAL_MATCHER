from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Callable, Iterable, Mapping

import numpy as np

from material_matcher.domain.errors import DomainError
from material_matcher.domain.models import MatchingConfig
from material_matcher.embedding.base import EmbeddingProvider
from material_matcher.embedding.cache import EmbeddingCache
from material_matcher.embedding.text import build_retrieval_text, retrieval_text_signature
from material_matcher.ingestion.reader import (
    ORIGINAL_ROW_NUMBER_KEY,
    detect_layout,
    iter_tabular_rows_with_position,
)
from material_matcher.matching.scorer import (
    allowed_by_scope,
    decide_status,
    minimum_score_gap,
    score_candidate,
)
from material_matcher.vector.index import EmbeddedBBQFlatIndex


@dataclass(frozen=True)
class CandidateResult:
    rank: int
    group_code: str
    score: float
    raw_score: float
    critical_conflict: bool
    target_payload: dict[str, object]
    field_scores: list[dict[str, object]]
    target_row_number: int | None = None
    compared_field_count: int = 0
    compared_weight_coverage: float = 0.0
    auto_match_safe: bool = True
    child_profile_id: str | None = None
    child_profile_version: int | None = None
    child_profile_name: str | None = None
    target_file_id: str | None = None
    target_file_name: str | None = None


@dataclass(frozen=True)
class RowResult:
    source_row_id: str
    source_id: str
    source_payload: dict[str, object]
    status: str
    final_group_code: str | None
    first_score: float
    second_score: float
    score_gap: float
    critical_conflict: bool
    candidates: list[CandidateResult]
    source_row_number: int | None = None


def _to_plain(row: Mapping[str, object]) -> dict[str, object]:
    return {str(key): value for key, value in row.items()}


def _validate_source_columns(source_row: dict[str, object], config: MatchingConfig) -> None:
    source_headers = set(source_row.keys())
    for rule in config.rules:
        missing = [field for field in rule.source.fields if field not in source_headers]
        if missing:
            raise DomainError(
                "COLUMN_NOT_FOUND",
                f"客户字段不存在：{', '.join(missing)}",
                status_code=422,
            )
    if config.source_id_column and config.source_id_column not in source_headers:
        raise DomainError(
            "COLUMN_NOT_FOUND",
            f"客户物料编码字段“{config.source_id_column}”不存在",
            status_code=422,
        )
    if config.source_filter and config.source_filter.field not in source_headers:
        raise DomainError(
            "COLUMN_NOT_FOUND",
            f"源数据过滤字段“{config.source_filter.field}”不存在",
            status_code=422,
        )
    if config.scope_mode != "GLOBAL" and config.scope.source_field not in source_headers:
        raise DomainError(
            "COLUMN_NOT_FOUND",
            f"客户分类字段“{config.scope.source_field}”不存在",
            status_code=422,
        )
    if config.retrieval.source:
        missing = [field for field in config.retrieval.source.fields if field not in source_headers]
        if missing:
            raise DomainError(
                "COLUMN_NOT_FOUND",
                f"向量检索客户字段不存在：{', '.join(missing)}",
                status_code=422,
            )


def _validate_target_columns(
    rows: list[dict[str, object]],
    config: MatchingConfig,
    group_code_column: str,
) -> None:
    if not rows:
        return
    target_headers = set(rows[0].keys())
    if group_code_column not in target_headers:
        raise DomainError(
            "COLUMN_NOT_FOUND",
            f"集团码字段“{group_code_column}”不存在",
            status_code=422,
        )
    for rule in config.rules:
        missing = [field for field in rule.target.fields if field not in target_headers]
        if missing:
            raise DomainError(
                "COLUMN_NOT_FOUND",
                f"集团字段不存在：{', '.join(missing)}",
                status_code=422,
            )
    if config.scope_mode != "GLOBAL" and config.scope.target_field not in target_headers:
        raise DomainError(
            "COLUMN_NOT_FOUND",
            f"集团分类字段“{config.scope.target_field}”不存在",
            status_code=422,
        )


def load_target_rows(path: Path, *, max_target_rows: int) -> list[dict[str, object]]:
    """Compatibility helper returning only payloads; matching uses positioned rows."""
    return [row for _, row in load_target_rows_with_position(path, max_target_rows=max_target_rows)]


def load_target_rows_with_position(
    path: Path,
    *,
    max_target_rows: int,
) -> list[tuple[int, dict[str, object]]]:
    layout = detect_layout(path)
    if layout.row_count_estimate > max_target_rows:
        raise DomainError(
            "INDEX_NOT_READY",
            f"当前通用扫描后端最多处理 {max_target_rows} 条集团数据；该目录约 {layout.row_count_estimate} 条，请使用向量索引",
            status_code=409,
            details={
                "row_count_estimate": layout.row_count_estimate,
                "baseline_limit": max_target_rows,
            },
        )
    rows = [
        (position, _to_plain(row))
        for position, row in iter_tabular_rows_with_position(
            path,
            sheet_name=layout.sheet_name,
            header_row=layout.header_row,
        )
    ]
    if len(rows) > max_target_rows:
        raise DomainError(
            "INDEX_NOT_READY",
            "集团数据超过通用扫描后端限制，请使用向量索引",
            status_code=409,
        )
    return rows


def source_filter_allows(source_row: Mapping[str, object], config: MatchingConfig) -> bool:
    flt = config.source_filter
    if flt is None:
        return True
    raw = source_row.get(flt.field)
    text = "" if raw is None else str(raw).strip()
    values = [str(value).strip() for value in flt.values if str(value).strip()]
    if not values:
        return True
    if flt.match == "contains":
        hit = any(value and value in text for value in values) if text else False
    else:
        hit = text in values
    return hit if flt.mode == "include" else not hit


def _unsafe_match_status(config: MatchingConfig) -> str:
    return "REVIEW" if config.decision.review_enabled else "UNMATCHED"


def _row_result(
    source_row: dict[str, object],
    row_index: int,
    source_row_number: int,
    scored: list[tuple[float, str, dict[str, object], dict[str, object], int | None]],
    config: MatchingConfig,
) -> RowResult:
    scored.sort(key=lambda item: item[0], reverse=True)
    selected = scored[: config.decision.top_n]
    candidates = [
        CandidateResult(
            rank=rank,
            group_code=item[1],
            score=round(item[0], 4),
            raw_score=float(item[3]["raw_score"]),
            critical_conflict=bool(item[3]["critical_conflict"]),
            target_payload=item[2],
            field_scores=list(item[3]["field_scores"]),
            target_row_number=item[4],
            compared_field_count=int(item[3].get("compared_field_count", 0)),
            compared_weight_coverage=float(item[3].get("compared_weight_coverage", 0.0)),
            auto_match_safe=bool(item[3].get("auto_match_safe", True)),
        )
        for rank, item in enumerate(selected, start=1)
    ]
    first = candidates[0].score if candidates else 0.0
    second = candidates[1].score if len(candidates) > 1 else 0.0
    status = decide_status(first, config) if candidates else "UNMATCHED"

    if status == "MATCHED" and candidates and not candidates[0].auto_match_safe:
        status = _unsafe_match_status(config)

    if status == "MATCHED" and candidates:
        top_code = candidates[0].group_code
        competitor = next(
            (candidate for candidate in candidates[1:] if candidate.group_code != top_code),
            None,
        )
        required_gap = minimum_score_gap(config)
        if competitor is not None and first - competitor.score < required_gap:
            status = _unsafe_match_status(config)

    # 并列保护策略：tie_break=top1（默认）时同分并列自动取第一条；
    # tie_break=review 时同分不同码转人工。最小分差与 critical 冲突保护始终生效。
    if (
        status == "MATCHED"
        and config.decision.tie_break == "review"
        and config.decision.review_enabled
        and len(candidates) > 1
        and candidates[1].score == first
        and candidates[1].group_code != candidates[0].group_code
    ):
        status = "REVIEW"

    final = candidates[0].group_code if status == "MATCHED" and candidates else None
    source_id = (
        str(source_row.get(config.source_id_column) or row_index)
        if config.source_id_column
        else str(row_index)
    )
    return RowResult(
        str(row_index),
        source_id,
        source_row,
        status,
        final,
        first,
        second,
        round(first - second, 4),
        candidates[0].critical_conflict if candidates else False,
        candidates,
        source_row_number,
    )


def match_rows(
    source_path: Path,
    target_path: Path,
    *,
    config: MatchingConfig,
    group_code_column: str,
    max_target_rows: int,
    max_source_rows: int | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    on_batch: Callable[[list["RowResult"]], None] | None = None,
    batch_rows: int = 256,
) -> list[RowResult]:
    target_rows = load_target_rows_with_position(target_path, max_target_rows=max_target_rows)
    _validate_target_columns([row for _, row in target_rows], config, group_code_column)
    source_layout = detect_layout(source_path)
    total = (
        min(source_layout.row_count_estimate, max_source_rows)
        if max_source_rows is not None
        else source_layout.row_count_estimate
    )
    results: list[RowResult] = []
    for row_index, (source_row_number, source_raw) in enumerate(
        iter_tabular_rows_with_position(
            source_path,
            sheet_name=source_layout.sheet_name,
            header_row=source_layout.header_row,
            max_rows=max_source_rows,
        ),
        start=1,
    ):
        source_row = _to_plain(source_raw)
        if row_index == 1:
            _validate_source_columns(source_row, config)
        if not source_filter_allows(source_row, config):
            if on_progress:
                on_progress(row_index, max(total, row_index))
            continue
        scored: list[tuple[float, str, dict[str, object], dict[str, object], int | None]] = []
        for target_row_number, target_row in target_rows:
            if not allowed_by_scope(source_row, target_row, config):
                continue
            code = target_row.get(group_code_column)
            if code is None or str(code) == "":
                continue
            score = score_candidate(source_row, target_row, config)
            scored.append(
                (
                    score.display_score,
                    str(code),
                    target_row,
                    score.to_dict(),
                    target_row_number,
                )
            )
        results.append(_row_result(source_row, row_index, source_row_number, scored, config))
        if on_progress:
            on_progress(row_index, max(total, row_index))
        if on_batch and len(results) % max(1, batch_rows) == 0:
            on_batch(list(results[-batch_rows:]))
    return results


def match_rows_indexed(
    source_path: Path,
    *,
    index: EmbeddedBBQFlatIndex,
    provider: EmbeddingProvider,
    cache: EmbeddingCache,
    config: MatchingConfig,
    group_code_column: str,
    query_batch_size: int,
    max_source_rows: int | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    scan_workers: int = 0,
    match_workers: int = 0,
    on_batch: Callable[[list["RowResult"]], None] | None = None,
    batch_rows: int = 256,
    collect_results: bool = True,
    performance_metrics: dict[str, object] | None = None,
) -> list[RowResult]:
    """Match source rows through a reusable bounded candidate index.

    Large GLOBAL indexes use the index's ANN path and parallelize source queries.
    Result batches can be persisted immediately with collect_results=False so
    memory stays bounded by query/persist batch size instead of task row count.
    """
    if not collect_results and on_batch is None:
        raise ValueError("collect_results=False requires on_batch persistence callback")
    parse_started = time.perf_counter()
    source_layout = detect_layout(source_path)
    total = (
        min(source_layout.row_count_estimate, max_source_rows)
        if max_source_rows is not None
        else source_layout.row_count_estimate
    )
    if performance_metrics is not None:
        timings = performance_metrics.setdefault("timings", {})
        if isinstance(timings, dict):
            timings["parsing"] = float(timings.get("parsing", 0.0)) + (time.perf_counter() - parse_started)
        performance_metrics["worker_count"] = max(1, int(match_workers or scan_workers or 1))
        performance_metrics["batch_size"] = max(1, int(batch_rows))
        performance_metrics["query_batch_size"] = max(1, int(query_batch_size))
        performance_metrics["recall_top_k"] = max(config.retrieval.retrieval_top_k, config.decision.top_n)
        performance_metrics["persisted_top_n"] = config.decision.top_n

    def add_timing(name: str, elapsed: float) -> None:
        if performance_metrics is None:
            return
        timings = performance_metrics.setdefault("timings", {})
        if isinstance(timings, dict):
            timings[name] = float(timings.get(name, 0.0)) + float(elapsed)

    source_signature = retrieval_text_signature(config, "source")
    results: list[RowResult] = []
    persist_pending: list[RowResult] = []
    batch: list[tuple[int, int, dict[str, object]]] = []
    active_workers = max(0, int(match_workers or scan_workers))
    candidate_top_k = max(config.retrieval.retrieval_top_k, config.decision.top_n)

    def emit(result: RowResult) -> None:
        if collect_results:
            results.append(result)
        if on_batch:
            persist_pending.append(result)
            if len(persist_pending) >= max(1, batch_rows):
                on_batch(list(persist_pending))
                persist_pending.clear()

    def flush(items: list[tuple[int, int, dict[str, object]]]) -> None:
        if not items:
            return
        active_items: list[tuple[int, int, dict[str, object]]] = []
        for row_index, source_row_number, source_row in items:
            if source_filter_allows(source_row, config):
                active_items.append((row_index, source_row_number, source_row))
            elif on_progress:
                on_progress(row_index, max(total, row_index))
        if not active_items:
            return

        started = time.perf_counter()
        texts = [build_retrieval_text(row, config, "source") for _, _, row in active_items]
        add_timing("normalization", time.perf_counter() - started)

        started = time.perf_counter()
        vectors, _ = cache.get_or_embed(texts, source_signature, max(1, query_batch_size))
        add_timing("source preprocessing", time.perf_counter() - started)

        hits_list: list[list] | None = None
        if config.scope_mode == "GLOBAL":
            started = time.perf_counter()
            hits_list = index.search_many(
                np.asarray(vectors, dtype=np.float32),
                candidate_top_k,
                oversample=config.retrieval.oversample,
                scan_workers=active_workers,
            )
            add_timing("retrieval", time.perf_counter() - started)

        for position, (row_index, source_row_number, source_row) in enumerate(active_items):
            query = np.asarray(vectors[position], dtype=np.float32)
            if hits_list is not None:
                hits = hits_list[position]
            else:
                started = time.perf_counter()
                candidate_ids = index.candidate_ids_for_scope(source_row, config)
                hits = index.search(
                    query,
                    candidate_top_k,
                    candidate_ids=candidate_ids,
                    oversample=config.retrieval.oversample,
                )
                add_timing("retrieval", time.perf_counter() - started)

            if performance_metrics is not None:
                counts = performance_metrics.setdefault("_candidate_counts", [])
                if isinstance(counts, list):
                    counts.append(len(hits))

            started = time.perf_counter()
            records = index.records([hit.row_id for hit in hits])
            scored: list[tuple[float, str, dict[str, object], dict[str, object], int | None]] = []
            for hit in hits:
                target_record = dict(records[hit.row_id])
                raw_target_row_number = target_record.pop(ORIGINAL_ROW_NUMBER_KEY, None)
                target_row_number = (
                    int(raw_target_row_number)
                    if raw_target_row_number is not None
                    else None
                )
                target_row = _to_plain(target_record)
                code = target_row.get(group_code_column)
                if code is None or str(code) == "":
                    continue
                semantic = max(0.0, min(1.0, float(hit.score)))
                score = score_candidate(
                    source_row,
                    target_row,
                    config,
                    semantic_score=semantic,
                )
                scored.append(
                    (
                        score.display_score,
                        str(code),
                        target_row,
                        score.to_dict(),
                        target_row_number,
                    )
                )
            add_timing("rerank/scoring", time.perf_counter() - started)

            started = time.perf_counter()
            result = _row_result(source_row, row_index, source_row_number, scored, config)
            add_timing("decision", time.perf_counter() - started)
            emit(result)
            if on_progress:
                on_progress(row_index, max(total, row_index))

    source_iterator = iter(iter_tabular_rows_with_position(
        source_path,
        sheet_name=source_layout.sheet_name,
        header_row=source_layout.header_row,
        max_rows=max_source_rows,
    ))
    row_index = 0
    while True:
        started = time.perf_counter()
        try:
            source_row_number, source_raw = next(source_iterator)
        except StopIteration:
            add_timing("parsing", time.perf_counter() - started)
            break
        add_timing("parsing", time.perf_counter() - started)
        row_index += 1
        started = time.perf_counter()
        source_row = _to_plain(source_raw)
        add_timing("normalization", time.perf_counter() - started)
        if row_index == 1:
            _validate_source_columns(source_row, config)
        batch.append((row_index, source_row_number, source_row))
        if len(batch) >= max(1, query_batch_size):
            flush(batch)
            batch = []
    flush(batch)
    if on_batch and persist_pending:
        on_batch(list(persist_pending))
        persist_pending.clear()
    if collect_results:
        results.sort(key=lambda item: int(item.source_row_id))
    return results


def summarize(rows: Iterable[RowResult]) -> dict[str, int]:
    summary = {"total": 0, "matched": 0, "review": 0, "unmatched": 0}
    for row in rows:
        summary["total"] += 1
        if row.status == "MATCHED":
            summary["matched"] += 1
        elif row.status == "REVIEW":
            summary["review"] += 1
        else:
            summary["unmatched"] += 1
    return summary
