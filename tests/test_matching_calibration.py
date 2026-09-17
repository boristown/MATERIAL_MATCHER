from __future__ import annotations

import csv
from pathlib import Path

from material_matcher.domain.models import MatchingConfig
from material_matcher.matching.engine import _row_result, match_rows
from material_matcher.matching.scorer import score_candidate
from material_matcher.normalize.pipeline import apply_processing_pipeline


def _pipe(value: str, op: str, options: dict[str, object] | None = None) -> str | None:
    return apply_processing_pipeline(value, [{"op": op, "options": options or {}}]).text


def test_generic_business_normalizers_cover_real_world_format_variants() -> None:
    standards = {
        _pipe("GB/T 1303.1-1998", "standard_number_normalize"),
        _pipe("GBT1303.1-1998", "standard_number_normalize"),
        _pipe("GB-T 1303.1-1998", "standard_number_normalize"),
        _pipe("ＧＢ／Ｔ １３０３．１－１９９８", "standard_number_normalize"),
    }
    assert standards == {"GB/T1303.1-1998"}

    specs = {
        _pipe("φ 8 mm", "specification_normalize"),
        _pipe("Φ8", "specification_normalize"),
        _pipe("∅8毫米", "specification_normalize"),
    }
    assert specs == {"Φ8"}
    assert _pipe("8 * 10 mm", "specification_normalize") == "8×10"
    assert _pipe("  jt 54ls14k  ", "model_normalize") == "JT54LS14K"

    manufacturers = {
        _pipe("天水华天微电子有限公司", "manufacturer_normalize"),
        _pipe("天水 华天微电子 公司", "manufacturer_normalize"),
    }
    assert manufacturers == {"天水华天微电子"}


def test_hybrid_containment_can_be_penalized_without_breaking_exact_equality() -> None:
    config = MatchingConfig.model_validate(
        {
            "rules": [
                {
                    "id": "model",
                    "source": {"fields": ["model"], "pipeline": [{"op": "model_normalize"}]},
                    "target": {"fields": ["model"], "pipeline": [{"op": "model_normalize"}]},
                    "matcher": "hybrid",
                    "matcher_options": {
                        "contains_score": 0.7,
                        "contains_length_sensitive": True,
                    },
                    "weight": 100,
                }
            ]
        }
    )
    exact = score_candidate({"model": "ABC123"}, {"model": "ABC123"}, config)
    extended = score_candidate({"model": "ABC123-NM0001"}, {"model": "ABC123"}, config)
    assert exact.display_score == 100.0
    assert extended.display_score < 100.0
    assert extended.display_score < exact.display_score


def test_dynamic_weight_exposes_weak_evidence_and_blocks_auto_release(tmp_path: Path) -> None:
    source_path = tmp_path / "source.csv"
    target_path = tmp_path / "target.csv"
    with source_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["id", "weak", "strong"])
        writer.writeheader()
        writer.writerow({"id": "S1", "weak": "同类", "strong": ""})
    with target_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["code", "weak", "strong"])
        writer.writeheader()
        writer.writerow({"code": "G1", "weak": "同类", "strong": ""})

    config = MatchingConfig.model_validate(
        {
            "source_id_column": "id",
            "rules": [
                {
                    "id": "weak",
                    "source": {"fields": ["weak"]},
                    "target": {"fields": ["weak"]},
                    "matcher": "exact",
                    "weight": 10,
                },
                {
                    "id": "strong",
                    "source": {"fields": ["strong"]},
                    "target": {"fields": ["strong"]},
                    "matcher": "exact",
                    "weight": 90,
                },
            ],
            "decision": {
                "success_threshold": 88,
                "review_enabled": True,
                "review_threshold": 70,
                "top_n": 5,
            },
            "advanced": {
                "matching_safety": {
                    "minimum_compared_field_count": 2,
                    "minimum_compared_weight_coverage": 0.5,
                }
            },
        }
    )
    candidate = score_candidate({"weak": "同类", "strong": ""}, {"weak": "同类", "strong": ""}, config)
    assert candidate.display_score == 100.0  # dynamic weighting itself stays transparent
    assert candidate.compared_field_count == 1
    assert candidate.compared_weight_coverage == 0.1
    assert candidate.auto_match_safe is False

    rows = match_rows(
        source_path,
        target_path,
        config=config,
        group_code_column="code",
        max_target_rows=100,
    )
    assert rows[0].first_score == 100.0
    assert rows[0].status == "REVIEW"
    assert rows[0].final_group_code is None


def test_minimum_score_gap_routes_near_tie_to_review() -> None:
    config = MatchingConfig.model_validate(
        {
            "source_id_column": "id",
            "rules": [
                {
                    "id": "name",
                    "source": {"fields": ["name"]},
                    "target": {"fields": ["name"]},
                    "matcher": "exact",
                    "weight": 90,
                },
                {
                    "id": "detail",
                    "source": {"fields": ["detail"]},
                    "target": {"fields": ["detail"]},
                    "matcher": "exact",
                    "weight": 10,
                },
            ],
            "decision": {
                "success_threshold": 88,
                "review_enabled": True,
                "review_threshold": 70,
                "top_n": 5,
            },
            "advanced": {"matching_safety": {"minimum_score_gap": 11}},
        }
    )
    source = {"id": "S1", "name": "轴承", "detail": "A"}
    targets = [
        ("G1", {"name": "轴承", "detail": "A"}, 2),
        ("G2", {"name": "轴承", "detail": "B"}, 3),
    ]
    scored = []
    for code, target, row_number in targets:
        score = score_candidate(source, target, config)
        scored.append((score.display_score, code, target, score.to_dict(), row_number))
    row = _row_result(source, 1, 2, scored, config)

    assert row.first_score == 100.0
    assert row.second_score == 90.0
    assert row.score_gap == 10.0
    assert row.status == "REVIEW"
