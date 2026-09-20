from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

CombineMode = Literal["concat", "coalesce", "best_of"]
MatcherMode = Literal["exact", "contains", "fuzzy", "semantic", "hybrid", "numeric"]


class ProcessingStep(BaseModel):
    op: str = "identity"
    options: dict[str, object] = Field(default_factory=dict)


class FieldSide(BaseModel):
    fields: list[str] = Field(default_factory=list)
    fixed_value: str | None = None
    combine: CombineMode = "concat"
    separator: str = " "
    pipeline: list[ProcessingStep] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_field_or_fixed_value(self) -> "FieldSide":
        fixed = None if self.fixed_value is None else str(self.fixed_value)
        has_fixed = fixed is not None and fixed.strip() != ""
        if has_fixed and self.fields:
            raise ValueError("字段侧不能同时配置字段和固定值")
        if not has_fixed and not self.fields:
            raise ValueError("字段侧至少选择一个字段或设置一个固定值")
        return self


class FieldRule(BaseModel):
    id: str
    source: FieldSide
    target: FieldSide
    matcher: MatcherMode = "fuzzy"
    weight: int = Field(ge=0, le=100)
    critical: bool = False
    matcher_options: dict[str, object] = Field(default_factory=dict)
    value_mapping: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def numeric_requires_tolerance(self) -> "FieldRule":
        if self.matcher == "numeric" and "tolerance" not in self.matcher_options:
            raise ValueError("数值匹配必须显式配置 tolerance，系统不会默认使用 2% 容差")
        return self


class DecisionConfig(BaseModel):
    success_threshold: int = Field(default=88, ge=0, le=100)
    review_enabled: bool = True
    review_threshold: int = Field(default=75, ge=0, le=100)
    top_n: int = Field(default=5, ge=1, le=50)

    @model_validator(mode="after")
    def validate_thresholds(self) -> "DecisionConfig":
        if self.review_enabled and self.review_threshold >= self.success_threshold:
            raise ValueError("人工确认下限必须小于自动匹配成功阈值")
        return self


class SourceFilter(BaseModel):
    field: str = Field(min_length=1, max_length=200)
    values: list[str] = Field(default_factory=list, max_length=500)
    mode: Literal["include", "exclude"] = "include"
    match: Literal["exact", "contains"] = "exact"

    @model_validator(mode="after")
    def require_values(self) -> "SourceFilter":
        if not any(str(value).strip() for value in self.values):
            raise ValueError("过滤条件至少需要一个非空值")
        return self


class ScopeConfig(BaseModel):
    source_field: str | None = None
    target_field: str | None = None
    mapping: dict[str, list[str]] = Field(default_factory=dict)


class RetrievalConfig(BaseModel):
    mode: Literal["auto", "scan", "vector"] = "auto"
    provider: str = "onnx_local"
    model_id: str = "BAAI/bge-base-zh-v1.5"
    dimensions: int = Field(default=768, ge=8, le=8192)
    max_length: int = Field(default=256, ge=16, le=4096)
    precision: str = "int8"
    source: FieldSide | None = None
    target: FieldSide | None = None
    retrieval_top_k: int = Field(default=200, ge=1, le=5000)
    oversample: int = Field(default=4, ge=1, le=32)


class MatchingConfig(BaseModel):
    source_id_column: str | None = None
    scope_mode: Literal["GLOBAL", "STRICT", "MAPPED"] = "GLOBAL"
    scope: ScopeConfig = Field(default_factory=ScopeConfig)
    source_filter: SourceFilter | None = None
    rules: list[FieldRule] = Field(default_factory=list)
    decision: DecisionConfig = Field(default_factory=DecisionConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    advanced: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_config(self) -> "MatchingConfig":
        if self.rules and sum(rule.weight for rule in self.rules) <= 0:
            raise ValueError("至少一个字段权重必须大于 0")
        if self.scope_mode in {"STRICT", "MAPPED"}:
            if not self.scope.source_field or not self.scope.target_field:
                raise ValueError("同组/分类映射匹配必须指定客户和集团分类字段")
        if self.scope_mode == "MAPPED" and not self.scope.mapping:
            raise ValueError("分类映射匹配必须配置分类映射")
        if self.retrieval.retrieval_top_k < self.decision.top_n:
            raise ValueError("向量召回 TopK 不能小于最终候选 TopN")
        return self
