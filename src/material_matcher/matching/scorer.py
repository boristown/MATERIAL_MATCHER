from __future__ import annotations

from dataclasses import dataclass, asdict
from difflib import SequenceMatcher
import math
from typing import Mapping

from material_matcher.domain.errors import DomainError
from material_matcher.domain.models import FieldRule, FieldSide, MatchingConfig
from collections import OrderedDict

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


@dataclass(frozen=True)
class CandidateScore:
    raw_score: float
    display_score: float
    field_scores: list[FieldScore]
    critical_conflict: bool

    def to_dict(self) -> dict[str, object]:
        return {"raw_score": self.raw_score, "display_score": self.display_score, "critical_conflict": self.critical_conflict, "field_scores": [asdict(item) for item in self.field_scores]}


def _pipeline_dicts(side: FieldSide) -> list[dict[str, object]]:
    # FieldSide instances are immutable pydantic objects owned by one frozen task
    # snapshot, so dumping them once per side keeps the normalize-memo keys stable
    # and removes per-pair model_dump churn from the scoring hot path.
    from collections import OrderedDict
    cache = _PIPELINE_DUMP_CACHE
    sid = id(side)
    hit = cache.get(sid)
    if hit is not None and hit[0] is side:
        return hit[1]
    dumped = [step.model_dump(mode="json") for step in side.pipeline]
    if len(cache) > 4096:
        cache.popitem(last=False)
    cache[sid] = (side, dumped)
    return dumped


def _trace_dicts(value: ProcessedValue) -> list[dict[str, object]]:
    return [{"operator": item.operator, "options": item.options, "input_preview": item.input_preview, "output_preview": item.output_preview} for item in value.trace]


def prepare_side_values(row: Mapping[str, object], side: FieldSide) -> list[ProcessedValue]:
    raw_values = [row.get(field) for field in side.fields]
    pipeline = _pipeline_dicts(side)
    if side.combine == "best_of":
        return [apply_processing_pipeline(value, pipeline) for value in raw_values if value is not None and str(value) != ""]
    if side.combine == "coalesce":
        chosen = next((value for value in raw_values if value is not None and str(value) != ""), None)
        return [apply_processing_pipeline(chosen, pipeline)]
    parts = [str(value) for value in raw_values if value is not None and str(value) != ""]
    return [apply_processing_pipeline(side.separator.join(parts) if parts else None, pipeline)]


def _numeric_score(source: str, target: str, tolerance: object) -> float:
    try:
        left = float(source); right = float(target)
    except ValueError:
        return 0.0
    if not isinstance(tolerance, dict):
        raise DomainError("NUMERIC_TOLERANCE_REQUIRED", "数值匹配必须显式配置 tolerance", status_code=422)
    mode = str(tolerance.get("mode", "")); delta = left - right
    if mode == "exact": return 1.0 if left == right else 0.0
    if mode == "absolute": return 1.0 if abs(delta) <= float(tolerance.get("value", 0.0)) else 0.0
    if mode == "relative": return 1.0 if abs(delta) / max(abs(right), 1e-12) <= float(tolerance.get("value", 0.0)) else 0.0
    if mode == "range": return 1.0 if float(tolerance.get("min_delta", 0.0)) <= delta <= float(tolerance.get("max_delta", 0.0)) else 0.0
    raise DomainError("NUMERIC_TOLERANCE_REQUIRED", "数值 tolerance 模式无效", status_code=422)


def _token_jaccard(source: str, target: str) -> float:
    left = set(source.split()); right = set(target.split())
    return len(left & right) / len(left | right) if left and right else 0.0


def _score_pair(source: str, target: str, rule: FieldRule, semantic_score: float | None) -> float:
    if rule.matcher == "exact": return 1.0 if source == target else 0.0
    if rule.matcher == "contains": return 1.0 if source in target or target in source else 0.0
    if rule.matcher == "fuzzy": return SequenceMatcher(None, source, target, autojunk=False).ratio()
    if rule.matcher == "hybrid":
        fuzzy = SequenceMatcher(None, source, target, autojunk=False).ratio(); token = _token_jaccard(source, target); contains = 1.0 if source in target or target in source else 0.0
        if bool(rule.matcher_options.get("include_semantic")):
            if semantic_score is None:
                raise DomainError("SEMANTIC_PROVIDER_NOT_READY", "该综合匹配规则已启用语义分，需要可用的 Embedding Provider 与向量索引", status_code=409)
            return max(fuzzy, token, contains, semantic_score)
        return max(fuzzy, token, contains)
    if rule.matcher == "numeric": return _numeric_score(source, target, rule.matcher_options.get("tolerance"))
    if rule.matcher == "semantic":
        if semantic_score is None:
            raise DomainError("SEMANTIC_PROVIDER_NOT_READY", "语义匹配需要可用的 Embedding Provider 与向量索引", status_code=409)
        return semantic_score
    raise DomainError("MATCHER_NOT_FOUND", f"不支持的匹配方式：{rule.matcher}", status_code=422)


def score_field_rule(source_row: Mapping[str, object], target_row: Mapping[str, object], rule: FieldRule, *, semantic_score: float | None = None) -> FieldScore | None:
    source_values = [v for v in prepare_side_values(source_row, rule.source) if not v.is_missing and v.text not in {None, ""}]
    target_values = [v for v in prepare_side_values(target_row, rule.target) if not v.is_missing and v.text not in {None, ""}]
    if not source_values or not target_values: return None
    best_score = -math.inf; best_source: ProcessedValue | None = None; best_target: ProcessedValue | None = None
    for source in source_values:
        for target in target_values:
            score = _score_pair(source.text or "", target.text or "", rule, semantic_score)
            if score > best_score: best_score=score; best_source=source; best_target=target
    assert best_source is not None and best_target is not None
    conflict = bool(rule.critical and best_score <= 0.0)
    return FieldScore(rule.id, max(0.0,min(1.0,float(best_score))), rule.weight, best_source.text or "", best_target.text or "", rule.critical, conflict, _trace_dicts(best_source), _trace_dicts(best_target))


def score_candidate(source_row: Mapping[str, object], target_row: Mapping[str, object], config: MatchingConfig, *, semantic_score: float | None = None) -> CandidateScore:
    scores: list[FieldScore] = []; weighted=0.0; matched_weight=0
    for rule in config.rules:
        result=score_field_rule(source_row,target_row,rule,semantic_score=semantic_score)
        if result is None or rule.weight <= 0: continue
        scores.append(result); weighted += result.score*rule.weight; matched_weight += rule.weight
    raw=weighted/matched_weight if matched_weight else 0.0
    return CandidateScore(raw, round(raw*100.0,4), scores, any(item.conflict for item in scores))


def allowed_by_scope(source_row: Mapping[str, object], target_row: Mapping[str, object], config: MatchingConfig) -> bool:
    if config.scope_mode == "GLOBAL": return True
    source_field=config.scope.source_field; target_field=config.scope.target_field
    if not source_field or not target_field: return False
    source_value=source_row.get(source_field); target_value=target_row.get(target_field)
    if source_value is None or target_value is None: return False
    if config.scope_mode == "STRICT": return str(source_value)==str(target_value)
    return str(target_value) in {str(v) for v in config.scope.mapping.get(str(source_value),[])}


def decide_status(score: float, config: MatchingConfig) -> str:
    if score > float(config.decision.success_threshold): return "MATCHED"
    if config.decision.review_enabled and score > float(config.decision.review_threshold): return "REVIEW"
    return "UNMATCHED"
