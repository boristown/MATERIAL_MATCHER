from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping

from material_matcher.domain.errors import DomainError
from material_matcher.domain.models import MatchingConfig
from material_matcher.ingestion.reader import detect_layout, iter_tabular_rows
from material_matcher.matching.scorer import allowed_by_scope, decide_status, score_candidate


@dataclass(frozen=True)
class CandidateResult:
    rank: int
    group_code: str
    score: float
    raw_score: float
    critical_conflict: bool
    target_payload: dict[str, object]
    field_scores: list[dict[str, object]]


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


def _to_plain(row: Mapping[str, object]) -> dict[str, object]:
    return {str(key): value for key, value in row.items()}


def _validate_columns(rows: list[dict[str, object]], config: MatchingConfig, group_code_column: str) -> None:
    if not rows:
        return
    target_headers = set(rows[0].keys())
    if group_code_column not in target_headers:
        raise DomainError("COLUMN_NOT_FOUND", f"集团码字段“{group_code_column}”不存在", status_code=422)
    for rule in config.rules:
        missing = [field for field in rule.target.fields if field not in target_headers]
        if missing:
            raise DomainError("COLUMN_NOT_FOUND", f"集团字段不存在：{', '.join(missing)}", status_code=422)
    if config.scope_mode != "GLOBAL" and config.scope.target_field not in target_headers:
        raise DomainError("COLUMN_NOT_FOUND", f"集团分类字段“{config.scope.target_field}”不存在", status_code=422)


def load_target_rows(path: Path, *, max_target_rows: int) -> list[dict[str, object]]:
    layout = detect_layout(path)
    if layout.row_count_estimate > max_target_rows:
        raise DomainError(
            "INDEX_NOT_READY",
            f"当前通用扫描后端最多处理 {max_target_rows} 条集团数据；该目录约 {layout.row_count_estimate} 条，请先构建向量索引",
            status_code=409,
            details={"row_count_estimate": layout.row_count_estimate, "baseline_limit": max_target_rows},
        )
    rows = [_to_plain(row) for row in iter_tabular_rows(path)]
    if len(rows) > max_target_rows:
        raise DomainError("INDEX_NOT_READY", "集团数据超过通用扫描后端限制，请先构建向量索引", status_code=409)
    return rows


def match_rows(
    source_path: Path,
    target_path: Path,
    *,
    config: MatchingConfig,
    group_code_column: str,
    max_target_rows: int,
    max_source_rows: int | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[RowResult]:
    target_rows = load_target_rows(target_path, max_target_rows=max_target_rows)
    _validate_columns(target_rows, config, group_code_column)
    source_layout = detect_layout(source_path)
    total = source_layout.row_count_estimate
    if max_source_rows is not None:
        total = min(total, max_source_rows)
    results: list[RowResult] = []
    for row_index, source_row_raw in enumerate(iter_tabular_rows(source_path, max_rows=max_source_rows), start=1):
        source_row = _to_plain(source_row_raw)
        if row_index == 1:
            source_headers = set(source_row.keys())
            for rule in config.rules:
                missing = [field for field in rule.source.fields if field not in source_headers]
                if missing:
                    raise DomainError("COLUMN_NOT_FOUND", f"客户字段不存在：{', '.join(missing)}", status_code=422)
            if config.source_id_column and config.source_id_column not in source_headers:
                raise DomainError("COLUMN_NOT_FOUND", f"客户物料编码字段“{config.source_id_column}”不存在", status_code=422)
            if config.scope_mode != "GLOBAL" and config.scope.source_field not in source_headers:
                raise DomainError("COLUMN_NOT_FOUND", f"客户分类字段“{config.scope.source_field}”不存在", status_code=422)
        scored: list[tuple[float, str, dict[str, object], dict[str, object]]] = []
        for target_row in target_rows:
            if not allowed_by_scope(source_row, target_row, config):
                continue
            group_code_value = target_row.get(group_code_column)
            if group_code_value is None or str(group_code_value) == "":
                continue
            score = score_candidate(source_row, target_row, config)
            scored.append((score.display_score, str(group_code_value), target_row, score.to_dict()))
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
            )
            for rank, item in enumerate(selected, start=1)
        ]
        first_score = candidates[0].score if candidates else 0.0
        second_score = candidates[1].score if len(candidates) > 1 else 0.0
        gap = round(first_score - second_score, 4)
        status = decide_status(first_score, config) if candidates else "UNMATCHED"
        final_group_code = candidates[0].group_code if status == "MATCHED" and candidates else None
        source_id = str(source_row.get(config.source_id_column) or row_index) if config.source_id_column else str(row_index)
        results.append(
            RowResult(
                source_row_id=str(row_index),
                source_id=source_id,
                source_payload=source_row,
                status=status,
                final_group_code=final_group_code,
                first_score=first_score,
                second_score=second_score,
                score_gap=gap,
                critical_conflict=candidates[0].critical_conflict if candidates else False,
                candidates=candidates,
            )
        )
        if on_progress:
            on_progress(row_index, max(total, row_index))
    return results


def summarize(rows: Iterable[RowResult]) -> dict[str, int]:
    summary = {"total": 0, "matched": 0, "review": 0, "unmatched": 0}
    for row in rows:
        summary["total"] += 1
        if row.status == "MATCHED": summary["matched"] += 1
        elif row.status == "REVIEW": summary["review"] += 1
        else: summary["unmatched"] += 1
    return summary
