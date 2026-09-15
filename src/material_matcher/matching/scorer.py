from __future__ import annotations

from dataclasses import dataclass, asdict
from difflib import SequenceMatcher
import math
from typing import Iterable, Mapping

from material_matcher.domain.errors import DomainError
from material_matcher.domain.models import FieldRule, FieldSide, MatchingConfig
from material_matcher.normalize.pipeline import ProcessedValue, apply_processing_pipeline


@dataclass(frozen=True)
class FieldScore:
    rule_id: str
    score: float
    weight: int
    source_value: str
    target_value: str
    critical: bool
    conflict: bool
    source_trace: list[dict[str, object]]
    target_trace: list[dict[str, object]]


@dataclass(frozen=True)
class CandidateScore:
    raw_score: float
    display_score: float
    field_scores: list[FieldScore]
    critical_conflict: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "raw_score": self.raw_score,
            "display_score": self.display_score,
            "critical_conflict": self.critical_conflict,
            "field_scores": [asdict(item) for item in self.field_scores],
        }


def _pipeline_dicts(side: FieldSide) -> list[dict[str, object]]:
    return [step.model_dump(mode="json") for step in side.pipeline]


def _trace_dicts(value: ProcessedValue) -> list[dict[str, object]]:
    return [
        {
            "operator": item.operator,
            "options": item.options,
            "input_preview": item.input_preview,
            "output_preview": item.output_preview,
        }
        for item in value.trace
    ]


def _prepare_values(row: Mapping[str, object], side: FieldSide) -> list[ProcessedValue]:
    raw_values = [row.get(field) for field in side.fields]
    pipeline = _pipeline_dicts(side)
    if side.combine == "best_of":
        return [
            apply_processing_pipeline(value, pipeline)
            for value in raw_values
            if value is not None and str(value) != ""
        ]
    if side.combine == "coalesce":
        chosen = next((value for value in raw_values if value is not None and str(value) != ""), None)
        return [apply_processing_pipeline(chosen, pipeline)]
    # concat is literal by design: no implicit trim or null token handling.
    parts = [str(value) for value in raw_values if value is not None and str(value) != ""]
    combined: object = side.separator.join(parts) if parts else None
    return [apply_processing_pipeline(combined, pipeline)]


def _numeric_score(source: str, target: str, tolerance: object) -> float:
    try:
        left = float(source); right = float(target)
    except ValueError:
        return 0.0
    if not isinstance(tolerance, dict):
        raise DomainError("NUMERIC_TOLERANCE_REQUIRED", "数值匹配必须显式配置 tolerance", status_code=422)
    mode = str(tolerance.get("mode", ""))
    delta = left - right
    if mode == "exact":
        return 1.0 if left == right else 0.0
    if mode == "absolute":
        limit = float(tolerance.get("value", 0.0))
        return 1.0 if abs(delta) <= limit else 0.0
    if mode == "relative":
        limit = float(tolerance.get("value", 0.0))
        denominator = max(abs(right), 1e-12)
        return 1.0 if abs(delta) / denominator <= limit else 0.0
    if mode == "range":
        return 1.0 if float(tolerance.get("min_delta", 0.0)) <= delta <= float(tolerance.get("max_delta", 0.0)) else 0.0
    raise DomainError("NUMERIC_TOLERANCE_REQUIRED", "数值 tolerance 模式无效", status_code=422)


def _token_jaccard(source: str, target: str) -> float:
    left = set(source.split()); right = set(target.split())
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _score_pair(source: str, target: str, rule: FieldRule) -> float:
    if rule.matcher == "exact":
        return 1.0 if source == target else 0.0
    if rule.matcher == "contains":
        return 1.0 if source in target or target in source else 0.0
    if rule.matcher == "fuzzy":
        return SequenceMatcher(None, source, target, autojunk=False).ratio()
    if rule.matcher == "hybrid":
        fuzzy = SequenceMatcher(None, source, target, autojunk=False).ratio()
        token = _token_jaccard(source, target)
        contains = 1.0 if source in target or target in source else 0.0
        return max(fuzzy, token, contains)
    if rule.matcher == "numeric":
        return _numeric_score(source, target, rule.matcher_options.get("tolerance"))
    if rule.matcher == "semantic":
        raise DomainError(
            "SEMANTIC_PROVIDER_NOT_READY",
            "当前里程碑尚未启用语义向量 Provider，请改用已启用的匹配方式或等待向量索引构建完成",
            status_code=409,
        )
    raise DomainError("MATCHER_NOT_FOUND", f"不支持的匹配方式：{rule.matcher}", status_code=422)


def score_field_rule(source_row: Mapping[str, object], target_row: Mapping[str, object], rule: FieldRule) -> FieldScore | None:
    source_values = [value for value in _prepare_values(source_row, rule.source) if not value.is_missing and value.text not in {None, ""}]
    target_values = [value for value in _prepare_values(target_row, rule.target) if not value.is_missing and value.text not in {None, ""}]
    if not source_values or not target_values:
        return None
    best_score = -math.inf
    best_source: ProcessedValue | None = None
    best_target: ProcessedValue | None = None
    for source in source_values:
        for target in target_values:
            score = _score_pair(source.text or "", target.text or "", rule)
            if score > best_score:
                best_score = score; best_source = source; best_target = target
    assert best_source is not None and best_target is not None
    conflict = bool(rule.critical and best_score <= 0.0)
    return FieldScore(
        rule_id=rule.id,
        score=max(0.0, min(1.0, float(best_score))),
        weight=rule.weight,
        source_value=best_source.text or "",
        target_value=best_target.text or "",
        critical=rule.critical,
        conflict=conflict,
        source_trace=_trace_dicts(best_source),
        target_trace=_trace_dicts(best_target),
    )


def score_candidate(source_row: Mapping[str, object], target_row: Mapping[str, object], config: MatchingConfig) -> CandidateScore:
    scores: list[FieldScore] = []
    weighted = 0.0; matched_weight = 0
    for rule in config.rules:
        result = score_field_rule(source_row, target_row, rule)
        if result is None or rule.weight <= 0:
            continue
        scores.append(result); weighted += result.score * rule.weight; matched_weight += rule.weight
    raw = weighted / matched_weight if matched_weight else 0.0
    return CandidateScore(
        raw_score=raw,
        display_score=round(raw * 100.0, 4),
        field_scores=scores,
        critical_conflict=any(item.conflict for item in scores),
    )


def allowed_by_scope(source_row: Mapping[str, object], target_row: Mapping[str, object], config: MatchingConfig) -> bool:
    if config.scope_mode == "GLOBAL":
        return True
    source_field = config.scope.source_field; target_field = config.scope.target_field
    if not source_field or not target_field:
        return False
    source_value = source_row.get(source_field); target_value = target_row.get(target_field)
    if source_value is None or target_value is None:
        return False
    if config.scope_mode == "STRICT":
        return str(source_value) == str(target_value)
    allowed = config.scope.mapping.get(str(source_value), [])
    return str(target_value) in {str(value) for value in allowed}


def decide_status(score: float, config: MatchingConfig) -> str:
    threshold = float(config.decision.success_threshold)
    review = float(config.decision.review_threshold)
    # Contract is strict > for automatic match.
    if score > threshold:
        return "MATCHED"
    if config.decision.review_enabled and score > review:
        return "REVIEW"
    return "UNMATCHED"
