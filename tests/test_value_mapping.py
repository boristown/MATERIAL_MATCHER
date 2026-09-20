from __future__ import annotations

from pathlib import Path

from material_matcher.domain.models import FieldRule, FieldSide, MatchingConfig, ProcessingStep
from material_matcher.embedding.text import build_retrieval_text, retrieval_text_signature
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
    assert result.field_scores[0].source_value_before_mapping == "10"
    assert result.field_scores[0].value_mapping_applied is True
    assert result.field_scores[0].unconfigured_source_values == ()


def test_value_mapping_is_used_by_default_source_retrieval_text() -> None:
    mapped = _config({"10": "国产", "11": "进口"})
    unmapped = _config({})

    assert build_retrieval_text({"物料编码": "S-1", "国产进口": "10"}, mapped, "source") == "国产"
    assert build_retrieval_text({"物料编码": "S-1", "国产进口": "10"}, unmapped, "source") == "10"
    assert retrieval_text_signature(mapped, "source") != retrieval_text_signature(unmapped, "source")


def test_unmapped_value_is_kept_and_never_auto_converted() -> None:
    result = score_candidate(
        {"物料编码": "S-1", "国产进口": "12"},
        {"国产进口": "国产"},
        _config({"10": "国产", "11": "进口"}),
    )

    assert result.display_score == 0.0
    assert result.field_scores[0].source_value == "12"
    assert result.field_scores[0].value_mapping_applied is False
    assert result.field_scores[0].unconfigured_source_values == ("12",)


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
    assert config.rules[0].value_mapping_source_values == []
    assert config.rules[0].value_mapping_target_values == []

    result = score_candidate(
        {"国产进口": "12"},
        {"国产进口": "国产"},
        config,
    )
    assert result.field_scores[0].unconfigured_source_values == ()


def test_profile_version_preserves_value_mapping(tmp_path: Path) -> None:
    meta = MetadataRepository(tmp_path / "meta.db")
    service = ProfileService(meta)
    document = _config({"10": "国产", "11": "进口"}).model_dump(mode="json")
    document["rules"][0]["value_mapping_source_values"] = ["10", "11"]
    document["rules"][0]["value_mapping_target_values"] = ["国产", "进口"]

    profile_id = str(service.create("枚举值映射方案", document)["profile_id"])
    published = service.publish(profile_id)
    saved = service.version(profile_id, int(published["version_no"]))["document"]

    assert saved["rules"][0]["value_mapping"] == {"10": "国产", "11": "进口"}
    assert saved["rules"][0]["value_mapping_source_values"] == ["10", "11"]
    assert saved["rules"][0]["value_mapping_target_values"] == ["国产", "进口"]


def test_editing_published_profile_creates_new_version_without_mutating_old_version(tmp_path: Path) -> None:
    meta = MetadataRepository(tmp_path / "meta.db")
    service = ProfileService(meta)

    v1_document = _config({}).model_dump(mode="json")
    profile_id = str(service.create("兼容旧方案", v1_document)["profile_id"])
    v1 = service.publish(profile_id)
    assert int(v1["version_no"]) == 1

    v2_document = _config({"10": "国产", "11": "进口"}).model_dump(mode="json")
    v2_document["rules"][0]["value_mapping_source_values"] = ["10", "11"]
    v2_document["rules"][0]["value_mapping_target_values"] = ["国产", "进口"]
    service.save_draft(profile_id, v2_document)
    v2 = service.publish(profile_id)

    assert int(v2["version_no"]) == 2
    assert service.version(profile_id, 1)["document"]["rules"][0]["value_mapping"] == {}
    assert service.version(profile_id, 2)["document"]["rules"][0]["value_mapping"] == {
        "10": "国产",
        "11": "进口",
    }
