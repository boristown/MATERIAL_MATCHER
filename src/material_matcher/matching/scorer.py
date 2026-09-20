from __future__ import annotations

from collections import OrderedDict
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
import math
from typing import Mapping

from material_matcher.domain.errors import DomainError
from material_matcher.domain.models import FieldRule, FieldSide, MatchingConfig
from material_matcher.normalize.pipeline import ProcessedValue, apply_processing_pipeline

_PIPELINE_DUMP_CACHE: "OrderedDict[int, tuple[object, list]]" = OrderedDict()


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
    source_value_before_mapping: str = ""
    value_mapping_applied: bool = False
    unconfigured_source_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class CandidateScore:
    raw_score: float
    display_score: float
    field_scores: list[FieldScore]
    critical_conflict: bool
    compared_field_count: int
    compared_weight: int
    configured_weight: int
    compared_weight_coverage: float
    auto_match_safe: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "raw_score": self.raw_score,
            "display_score": self.display_score,
            "critical_conflict": self.critical_conflict,
            "compared_field_count": self.compared_field_count,
            "compared_weight": self.compared_weight,
            "configured_weight": self.configured_weight,
            "compared_weight_coverage": self.compared_weight_coverage,
            "auto_match_safe": self.auto_match_safe,
            "field_scores": [asdict(item) for item in self.field_scores],
        }


def _pipeline_dicts(side: FieldSide) -> list[dict[str, object]]:
    # FieldSide instances are immutable pydantic objects owned by one frozen task
    # snapshot, so dumping them once per side keeps normalize-memo keys stable.
    sid = id(side)
    hit = _PIPELINE_DUMP_CACHE.get(sid)
    if hit is not None and hit[0] is side:
        return hit[1]
    dumped = [step.model_dump(mode="json") for step in side.pipeline]
    if len(_PIPELINE_DUMP_CACHE) > 4096:
        _PIPELINE_DUMP_CACHE.popitem(last=False)
    _PIPELINE_DUMP_CACHE[sid] = (side, dumped)
    return dumped


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


def prepare_side_values(
    row: Mapping[str, object],
    side: FieldSide,
    *,
    value_mapping: Mapping[str, str] | None = None,
) -> list[ProcessedValue]:
    pipeline = _pipeline_dicts(side)
    mapping = {str(key): str(value) for key, value in (value_mapping or {}).items()}

    def processed(value: object) -> ProcessedValue:
        initial = apply_processing_pipeline(value, pipeline)
        if not mapping or initial.text in {None, ""}:
            return initial
        mapped = mapping.get(initial.text or "")
        if mapped is None and value is not None:
            mapped = mapping.get(str(value))
        if mapped is None:
            return initial
        return apply_processing_pipeline(mapped, pipeline)

    if side.fixed_value is not None:
        return [processed(side.fixed_value)]
    raw_values = [row.get(field) for field in side.fields]
    if side.combine == "best_of":
        return [
            processed(value)
            for value in raw_values
            if value is not None and str(value) != ""
        ]
    if side.combine == "coalesce":
        chosen = next((value for value in raw_values if value is not None and str(value) != ""), None)
        return [processed(chosen)]
    parts = [str(value) for value in raw_values if value is not None and str(value) != ""]
    return [processed(side.separator.join(parts) if parts else None)]


def _numeric_score(source: str, target: str, tolerance: object) -> float:
    try:
        left = float(source)
        right = float(target)
    except ValueError:
        return 0.0
    if not isinstance(tolerance, dict):
        raise DomainError(
            "NUMERIC_TOLERANCE_REQUIRED",
            "数值匹配必须显式配置 tolerance",
            status_code=422,
        )
    mode = str(tolerance.get("mode", ""))
    delta = left - right
    if mode == "exact":
        return 1.0 if left == right else 0.0
    if mode == "absolute":
        return 1.0 if abs(delta) <= float(tolerance.get("value", 0.0)) else 0.0
    if mode == "relative":
        return 1.0 if abs(delta) / max(abs(right), 1e-12) <= float(tolerance.get("value", 0.0)) else 0.0
    if mode == "range":
        return 1.0 if float(tolerance.get("min_delta", 0.0)) <= delta <= float(tolerance.get("max_delta", 0.0)) else 0.0
    raise DomainError(
        "NUMERIC_TOLERANCE_REQUIRED",
        "数值 tolerance 模式无效",
        status_code=422,
    )


def _token_jaccard(source: str, target: str) -> float:
    left = set(source.split())
    right = set(target.split())
    return len(left & right) / len(left | right) if left and right else 0.0


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _containment_score(source: str, target: str, rule: FieldRule) -> float:
    if source == target:
        return 1.0
    if source not in target and target not in source:
        return 0.0
    score = _clamp01(float(rule.matcher_options.get("contains_score", 1.0)))
    if bool(rule.matcher_options.get("contains_length_sensitive", False)):
        shorter = min(len(source), len(target))
        longer = max(len(source), len(target), 1)
        score *= shorter / longer
    return _clamp01(score)


def _score_pair(source: str, target: str, rule: FieldRule, semantic_score: float | None) -> float:
    if rule.matcher == "exact":
        return 1.0 if source == target else 0.0
    if rule.matcher == "contains":
        return _containment_score(source, target, rule)
    if rule.matcher == "fuzzy":
        return SequenceMatcher(None, source, target, autojunk=False).ratio()
    if rule.matcher == "hybrid":
        fuzzy = SequenceMatcher(None, source, target, autojunk=False).ratio()
        token = _token_jaccard(source, target)
        contains = _containment_score(source, target, rule)
        if bool(rule.matcher_options.get("include_semantic")):
            if semantic_score is None:
                raise DomainError(
                    "SEMANTIC_PROVIDER_NOT_READY",
                    "该综合匹配规则已启用语义分，需要可用的 Embedding Provider 与向量索引",
                    status_code=409,
                )
            return max(fuzzy, token, contains, semantic_score)
        return max(fuzzy, token, contains)
    if rule.matcher == "numeric":
        return _numeric_score(source, target, rule.matcher_options.get("tolerance"))
    if rule.matcher == "semantic":
        if semantic_score is None:
            raise DomainError(
                "SEMANTIC_PROVIDER_NOT_READY",
                "语义匹配需要可用的 Embedding Provider 与向量索引",
                status_code=409,
            )
        return semantic_score
    raise DomainError(
        "MATCHER_NOT_FOUND",
        f"不支持的匹配方式：{rule.matcher}",
        status_code=422,
    )


def score_field_rule(
    source_row: Mapping[str, object],
    target_row: Mapping[str, object],
    rule: FieldRule,
    *,
    semantic_score: float | None = None,
) -> FieldScore | None:
    source_values_before_mapping = [
        value
        for value in prepare_side_values(source_row, rule.source)
        if not value.is_missing and value.text not in {None, ""}
    ]
    source_values = [
        value
        for value in prepare_side_values(source_row, rule.source, value_mapping=rule.value_mapping)
        if not value.is_missing and value.text not in {None, ""}
    ]
    target_values = [
        value
        for value in prepare_side_values(target_row, rule.target)
        if not value.is_missing and value.text not in {None, ""}
    ]
    if not source_values or not target_values:
        return None
    best_score = -math.inf
    best_source: ProcessedValue | None = None
    best_target: ProcessedValue | None = None
    for source in source_values:
        for target in target_values:
            score = _score_pair(source.text or "", target.text or "", rule, semantic_score)
            if score > best_score:
                best_score = score
                best_source = source
                best_target = target
    assert best_source is not None and best_target is not None
    conflict = bool(rule.critical and best_score <= 0.0)
    mapping = {str(key): str(value) for key, value in rule.value_mapping.items()}
    before_texts = [value.text or "" for value in source_values_before_mapping]
    unconfigured = tuple(
        text for text in before_texts
        if mapping and text and text not in mapping
    )
    mapping_applied = bool(mapping) and any(
        text in mapping and mapping[text] != text
        for text in before_texts
    )
    return FieldScore(
        rule_id=rule.id,
        score=_clamp01(float(best_score)),
        weight=rule.weight,
        source_value=best_source.text or "",
        target_value=best_target.text or "",
        critical=rule.critical,
        conflict=conflict,
        source_trace=_trace_dicts(best_source),
        target_trace=_trace_dicts(best_target),
        source_value_before_mapping=" / ".join(before_texts),
        value_mapping_applied=mapping_applied,
        unconfigured_source_values=unconfigured,
    )


def _matching_safety(config: MatchingConfig) -> tuple[int, float]:
    raw = config.advanced.get("matching_safety", {})
    if not isinstance(raw, Mapping):
        return 0, 0.0
    minimum_fields = max(0, int(raw.get("minimum_compared_field_count", 0) or 0))
    minimum_coverage = _clamp01(float(raw.get("minimum_compared_weight_coverage", 0.0) or 0.0))
    return minimum_fields, minimum_coverage


def minimum_score_gap(config: MatchingConfig) -> float:
    raw = config.advanced.get("matching_safety", {})
    if not isinstance(raw, Mapping):
        return 0.0
    return max(0.0, float(raw.get("minimum_score_gap", 0.0) or 0.0))


def score_candidate(
    source_row: Mapping[str, object],
    target_row: Mapping[str, object],
    config: MatchingConfig,
    *,
    semantic_score: float | None = None,
) -> CandidateScore:
    scores: list[FieldScore] = []
    weighted = 0.0
    compared_weight = 0
    configured_weight = sum(rule.weight for rule in config.rules if rule.weight > 0)
    for rule in config.rules:
        result = score_field_rule(source_row, target_row, rule, semantic_score=semantic_score)
        if result is None or rule.weight <= 0:
            continue
        scores.append(result)
        weighted += result.score * rule.weight
        compared_weight += rule.weight
    raw = weighted / compared_weight if compared_weight else 0.0
    coverage = compared_weight / configured_weight if configured_weight else 0.0
    minimum_fields, minimum_coverage = _matching_safety(config)
    safe = len(scores) >= minimum_fields and coverage >= minimum_coverage
    return CandidateScore(
        raw,
        round(raw * 100.0, 4),
        scores,
        any(item.conflict for item in scores),
        len(scores),
        compared_weight,
        configured_weight,
        round(coverage, 6),
        safe,
    )


def allowed_by_scope(
    source_row: Mapping[str, object],
    target_row: Mapping[str, object],
    config: MatchingConfig,
) -> bool:
    if config.scope_mode == "GLOBAL":
        return True
    source_field = config.scope.source_field
    target_field = config.scope.target_field
    if not source_field or not target_field:
        return False
    source_value = source_row.get(source_field)
    target_value = target_row.get(target_field)
    if source_value is None or target_value is None:
        return False
    if config.scope_mode == "STRICT":
        return str(source_value) == str(target_value)
    return str(target_value) in {str(value) for value in config.scope.mapping.get(str(source_value), [])}


def decide_status(score: float, config: MatchingConfig) -> str:
    if score > float(config.decision.success_threshold):
        return "MATCHED"
    if config.decision.review_enabled and score > float(config.decision.review_threshold):
        return "REVIEW"
    return "UNMATCHED"
