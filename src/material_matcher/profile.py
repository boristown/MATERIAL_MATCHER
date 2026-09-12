from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProfileMeta(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    version: int | str = 1
    status: str | None = None


class ProfileDocument(BaseModel):
    """Data-driven profile contract.

    Customer-specific fields remain dynamic. The core schema validates the
    reusable engine sections while allowing future plugin-specific options.
    """

    model_config = ConfigDict(extra="allow")

    profile: ProfileMeta
    source: dict[str, Any] | None = None
    datasets: dict[str, dict[str, Any]] = Field(default_factory=dict)
    joins: list[dict[str, Any]] = Field(default_factory=list)
    target: dict[str, Any] | None = None
    target_catalogs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    routing: dict[str, Any] | None = None
    logical_fields: dict[str, Any] = Field(default_factory=dict)
    transforms: dict[str, Any] = Field(default_factory=dict)
    normalization: dict[str, Any] = Field(default_factory=dict)
    dictionaries: dict[str, Any] = Field(default_factory=dict)
    match_rules: list[dict[str, Any]] = Field(default_factory=list)
    rule_sets: dict[str, Any] = Field(default_factory=dict)
    scoring: dict[str, Any] = Field(default_factory=dict)
    group_matching: dict[str, Any] = Field(default_factory=dict)
    retrieval: dict[str, Any] = Field(default_factory=dict)
    decision: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    runtime: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_data_endpoints(self) -> "ProfileDocument":
        if self.source is None and not self.datasets:
            raise ValueError("profile must define source or datasets")
        if self.target is None and not self.target_catalogs:
            raise ValueError("profile must define target or target_catalogs")
        if not self.logical_fields:
            raise ValueError("profile must define logical_fields")
        if not self.match_rules and not self.rule_sets:
            raise ValueError("profile must define match_rules or rule_sets")
        return self


class LoadedProfile(BaseModel):
    document: ProfileDocument
    sha256: str
    source_path: str


def load_profile(path: str | Path) -> LoadedProfile:
    profile_path = Path(path)
    raw_bytes = profile_path.read_bytes()
    raw = yaml.safe_load(raw_bytes) or {}
    if not isinstance(raw, dict):
        raise ValueError("profile root must be a mapping")
    document = ProfileDocument.model_validate(raw)
    digest = hashlib.sha256(raw_bytes).hexdigest()
    return LoadedProfile(document=document, sha256=digest, source_path=str(profile_path))
