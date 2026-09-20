from __future__ import annotations

from pathlib import Path

from material_matcher.domain.models import MatchingConfig
from material_matcher.ingestion.column_profile import profile_tabular_columns
from material_matcher.matching.scorer import score_candidate


def test_two_template_enum_mapping_end_to_end(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    target = tmp_path / "target.csv"
    source.write_text(
        "物料编码,产品名称,国产进口\n"
        "S001,高速轴承,10\n"
        "S002,工业电机,11\n"
        "S003,精密螺栓,10\n"
        "S004,控制继电器,11\n",
        encoding="utf-8",
    )
    target.write_text(
        "集团码,产品名称,国产进口\n"
        "G001,高速轴承,国产\n"
        "G002,工业电机,进口\n"
        "G003,精密螺栓,国产\n"
        "G004,控制继电器,进口\n",
        encoding="utf-8",
    )

    source_profile = profile_tabular_columns(source)
    target_profile = profile_tabular_columns(target)
    source_columns = {item["field_name"]: item for item in source_profile["columns"]}
    target_columns = {item["field_name"]: item for item in target_profile["columns"]}

    assert source_columns["国产进口"]["enum_candidate"] is True
    assert source_columns["国产进口"]["sample_values"] == ["10", "11"]
    assert target_columns["国产进口"]["enum_candidate"] is True
    assert target_columns["国产进口"]["sample_values"] == ["国产", "进口"]

    config = MatchingConfig.model_validate(
        {
            "source_id_column": "物料编码",
            "rules": [
                {
                    "id": "name",
                    "source": {"fields": ["产品名称"]},
                    "target": {"fields": ["产品名称"]},
                    "matcher": "exact",
                    "weight": 50,
                },
                {
                    "id": "origin",
                    "source": {"fields": ["国产进口"]},
                    "target": {"fields": ["国产进口"]},
                    "matcher": "exact",
                    "weight": 50,
                    "value_mapping": {"10": "国产", "11": "进口"},
                },
            ],
            "decision": {
                "success_threshold": 88,
                "review_enabled": True,
                "review_threshold": 75,
                "top_n": 5,
            },
        }
    )

    dumped = config.model_dump(mode="json")
    assert "review_threshold" not in dumped["decision"]
    assert dumped["rules"][1]["value_mapping"] == {"10": "国产", "11": "进口"}

    scored = score_candidate(
        {"物料编码": "S001", "产品名称": "高速轴承", "国产进口": "10"},
        {"集团码": "G001", "产品名称": "高速轴承", "国产进口": "国产"},
        config,
    )
    assert scored.display_score == 100.0
    assert scored.field_scores[1].source_value == "国产"
    assert scored.field_scores[1].value_mapping_applied is True


def test_current_business_match_modes_remain_valid() -> None:
    for matcher in ("exact", "semantic"):
        config = MatchingConfig.model_validate(
            {
                "rules": [
                    {
                        "id": matcher,
                        "source": {"fields": ["产品名称"]},
                        "target": {"fields": ["产品名称"]},
                        "matcher": matcher,
                        "weight": 100,
                    }
                ]
            }
        )
        assert config.rules[0].matcher == matcher
