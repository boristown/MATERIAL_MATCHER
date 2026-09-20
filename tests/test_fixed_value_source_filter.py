from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from material_matcher.domain.errors import DomainError
from material_matcher.domain.models import FieldRule, FieldSide, MatchingConfig, ProcessingStep, SourceFilter
from material_matcher.embedding.text import build_retrieval_text
from material_matcher.matching.engine import (
    _validate_source_columns,
    _validate_target_columns,
    source_filter_allows,
)
from material_matcher.matching.scorer import prepare_side_values, score_candidate
from material_matcher.services.profile_service import ProfileService
from material_matcher.storage.metadata import MetadataRepository


def _rule(source: FieldSide, target: FieldSide) -> FieldRule:
    return FieldRule(
        id="type",
        source=source,
        target=target,
        matcher="exact",
        weight=100,
        critical=False,
    )


def test_source_fixed_value_scores_and_participates_in_retrieval_text() -> None:
    config = MatchingConfig(
        source_id_column="物料编码",
        rules=[_rule(FieldSide(fixed_value="Z001"), FieldSide(fields=["物料类型"]))],
    )

    result = score_candidate(
        {"物料编码": "S-1", "描述": "螺栓"},
        {"物料类型": "Z001"},
        config,
    )

    assert result.display_score == 100.0
    assert result.field_scores[0].source_value == "Z001"
    assert build_retrieval_text({"物料编码": "S-1"}, config, "source") == "Z001"


def test_target_fixed_value_scores_normally() -> None:
    config = MatchingConfig(
        rules=[_rule(FieldSide(fields=["物料类型"]), FieldSide(fixed_value="Z001"))],
    )

    result = score_candidate({"物料类型": "Z001"}, {"任意字段": "ignored"}, config)

    assert result.display_score == 100.0
    assert result.field_scores[0].target_value == "Z001"


def test_fixed_value_runs_through_normalization_pipeline() -> None:
    side = FieldSide(
        fixed_value="  z001  ",
        pipeline=[
            ProcessingStep(op="trim"),
            ProcessingStep(op="case_map", options={"mode": "upper"}),
        ],
    )

    values = prepare_side_values({}, side)

    assert len(values) == 1
    assert values[0].text == "Z001"
    assert [item.operator for item in values[0].trace] == ["trim", "case_map"]


def test_fields_and_fixed_value_are_mutually_exclusive() -> None:
    with pytest.raises(ValidationError):
        FieldSide(fields=["物料类型"], fixed_value="Z001")

    with pytest.raises(ValidationError):
        FieldSide(fixed_value="   ")


def test_fixed_value_does_not_trigger_column_not_found() -> None:
    config = MatchingConfig(
        source_id_column="物料编码",
        rules=[_rule(FieldSide(fixed_value="Z001"), FieldSide(fixed_value="Z001"))],
    )

    _validate_source_columns({"物料编码": "S-1"}, config)
    _validate_target_columns([{"集团码": "G-1"}], config, "集团码")


def test_legacy_field_only_scheme_remains_compatible() -> None:
    config = MatchingConfig.model_validate(
        {
            "source_id_column": "物料编码",
            "rules": [
                {
                    "id": "desc",
                    "source": {
                        "fields": ["物料描述"],
                        "combine": "concat",
                        "separator": " ",
                        "pipeline": [],
                    },
                    "target": {
                        "fields": ["集团描述"],
                        "combine": "concat",
                        "separator": " ",
                        "pipeline": [],
                    },
                    "matcher": "exact",
                    "weight": 100,
                    "critical": False,
                }
            ],
        }
    )

    assert config.rules[0].source.fixed_value is None
    assert config.rules[0].target.fixed_value is None
    assert score_candidate(
        {"物料编码": "S-1", "物料描述": "A"},
        {"集团描述": "A"},
        config,
    ).display_score == 100.0


@pytest.mark.parametrize(
    ("mode", "match", "row_value", "expected"),
    [
        ("include", "exact", "Z001", True),
        ("include", "exact", "Z002", False),
        ("exclude", "exact", "Z001", False),
        ("exclude", "exact", "Z002", True),
        ("include", "contains", "TYPE-Z001-A", True),
        ("exclude", "contains", "TYPE-Z001-A", False),
    ],
)
def test_source_filter_include_exclude_exact_contains(
    mode: str,
    match: str,
    row_value: str,
    expected: bool,
) -> None:
    config = MatchingConfig(
        source_filter=SourceFilter(
            field="物料类型",
            values=["Z001"],
            mode=mode,
            match=match,
        )
    )

    assert source_filter_allows({"物料类型": row_value}, config) is expected


def test_source_filter_missing_column_fails_explicitly() -> None:
    config = MatchingConfig(
        source_id_column="物料编码",
        source_filter=SourceFilter(field="物料类型", values=["Z001"]),
        rules=[_rule(FieldSide(fixed_value="Z001"), FieldSide(fixed_value="Z001"))],
    )

    with pytest.raises(DomainError) as exc:
        _validate_source_columns({"物料编码": "S-1"}, config)

    assert exc.value.code == "COLUMN_NOT_FOUND"
    assert "源数据过滤字段" in exc.value.message


def test_published_profile_preserves_fixed_value_and_source_filter(tmp_path: Path) -> None:
    meta = MetadataRepository(tmp_path / "meta.db")
    service = ProfileService(meta)
    document = {
        "source_id_column": "物料编码",
        "source_filter": {
            "field": "物料类型",
            "values": ["Z001"],
            "mode": "include",
            "match": "contains",
        },
        "rules": [
            {
                "id": "type",
                "source": {
                    "fields": [],
                    "fixed_value": "Z001",
                    "combine": "concat",
                    "separator": " ",
                    "pipeline": [{"op": "case_map", "options": {"mode": "upper"}}],
                },
                "target": {
                    "fields": ["物料类型"],
                    "combine": "concat",
                    "separator": " ",
                    "pipeline": [],
                },
                "matcher": "exact",
                "weight": 100,
                "critical": False,
            }
        ],
    }

    profile_id = str(service.create("Z001 方案", document)["profile_id"])
    published = service.publish(profile_id)
    reloaded = service.version(profile_id, int(published["version_no"]))
    saved = reloaded["document"]

    assert saved["source_filter"] == {
        "field": "物料类型",
        "values": ["Z001"],
        "mode": "include",
        "match": "contains",
    }
    assert saved["rules"][0]["source"]["fields"] == []
    assert saved["rules"][0]["source"]["fixed_value"] == "Z001"
