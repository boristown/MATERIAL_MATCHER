from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

CombineMode = Literal["concat", "coalesce", "best_of"]
MatcherMode = Literal["exact", "contains", "fuzzy", "semantic", "hybrid", "numeric"]


class ProcessingStep(BaseModel):
    op: str = "identity"
    options: dict[str, object] = Field(default_factory=dict)


class FieldSide(BaseModel):
    fields: list[str] = Field(min_length=1)
    combine: CombineMode = "concat"
    separator: str = " "
    pipeline: list[ProcessingStep] = Field(default_factory=list)


class FieldRule(BaseModel):
    id: str
    source: FieldSide
    target: FieldSide
    matcher: MatcherMode = "fuzzy"
    weight: int = Field(ge=0, le=100)
    critical: bool = False
    matcher_options: dict[str, object] = Field(default_factory=dict)

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


class ScopeConfig(BaseModel):
    source_field: str | None = None
    target_field: str | None = None
    mapping: dict[str, list[str]] = Field(default_factory=dict)


class MatchingConfig(BaseModel):
    source_id_column: str | None = None
    scope_mode: Literal["GLOBAL", "STRICT", "MAPPED"] = "GLOBAL"
    scope: ScopeConfig = Field(default_factory=ScopeConfig)
    rules: list[FieldRule] = Field(default_factory=list)
    decision: DecisionConfig = Field(default_factory=DecisionConfig)
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
        return self
