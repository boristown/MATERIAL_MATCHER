from __future__ import annotations

from pathlib import Path

from material_matcher.domain.models import FieldRule, FieldSide, MatchingConfig, ProcessingStep
from material_matcher.matching.scorer import score_candidate
from material_matcher.services.profile_service import ProfileService
from material_matcher.storage.metadata import MetadataRepository


def _config(mapping: dict[str, str]) -> MatchingConfig:
    return MatchingConfig(
        source_id_column="物料编码",
        rules=[
            FieldRule(
                id="origin",
                source=FieldSide(
                    fields=["国产进口"],
                    pipeline=[ProcessingStep(op="trim")],
                ),
                target=FieldSide(fields=["国产进口"]),
                matcher="exact",
                weight=100,
                value_mapping=mapping,
            )
        ],
    )


def test_value_mapping_converts_source_value_before_scoring() -> None:
    result = score_candidate(
        {"物料编码": "S-1", "国产进口": " 10 "},
        {"国产进口": "国产"},
        _config({"10": "国产", "11": "进口"}),
    )

    assert result.display_score == 100.0
    assert result.field_scores[0].source_value == "国产"
    assert result.field_scores[0].target_value == "国产"


def test_unmapped_value_is_kept_and_never_auto_converted() -> None:
    result = score_candidate(
        {"物料编码": "S-1", "国产进口": "12"},
        {"国产进口": "国产"},
        _config({"10": "国产", "11": "进口"}),
    )

    assert result.display_score == 0.0
    assert result.field_scores[0].source_value == "12"


def test_legacy_rule_without_value_mapping_remains_compatible() -> None:
    config = MatchingConfig.model_validate(
        {
            "rules": [
                {
                    "id": "origin",
                    "source": {"fields": ["国产进口"]},
                    "target": {"fields": ["国产进口"]},
                    "matcher": "exact",
                    "weight": 100,
                }
            ]
        }
    )

    assert config.rules[0].value_mapping == {}


def test_profile_version_preserves_value_mapping(tmp_path: Path) -> None:
    meta = MetadataRepository(tmp_path / "meta.db")
    service = ProfileService(meta)
    document = _config({"10": "国产", "11": "进口"}).model_dump(mode="json")

    profile_id = str(service.create("枚举值映射方案", document)["profile_id"])
    published = service.publish(profile_id)
    saved = service.version(profile_id, int(published["version_no"]))["document"]

    assert saved["rules"][0]["value_mapping"] == {"10": "国产", "11": "进口"}
