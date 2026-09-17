from __future__ import annotations

import csv
import json
from collections import defaultdict

from evaluate_matching_quality import (
    SOURCE_PATH,
    TARGET_PATH,
    TRUTH_PATH,
    build_config,
)
from material_matcher.matching.engine import RowResult, match_rows


def _truth() -> dict[str, dict[str, str]]:
    with TRUTH_PATH.open("r", encoding="utf-8-sig", newline="") as stream:
        return {row["物料编码"]: row for row in csv.DictReader(stream)}


def _field_breakdown(row: RowResult) -> list[dict[str, object]]:
    if not row.candidates:
        return []
    candidate = row.candidates[0]
    return [
        {
            "rule_id": field["rule_id"],
            "score": round(float(field["score"]), 4),
            "weight": int(field["weight"]),
            "source": str(field["source_value"])[:120],
            "target": str(field["target_value"])[:120],
        }
        for field in candidate.field_scores
    ]


def _sample(row: RowResult, truth: dict[str, str]) -> dict[str, object]:
    return {
        "material_code": row.source_id,
        "material_type": truth["物料类型"],
        "scenario": truth["场景"],
        "expected_match": truth["预期是否可匹配"],
        "expected_group_code": truth["预期集团码"] or None,
        "top1_group_code": row.candidates[0].group_code if row.candidates else None,
        "first_score": row.first_score,
        "second_score": row.second_score,
        "score_gap": row.score_gap,
        "status": row.status,
        "compared_field_count": row.candidates[0].compared_field_count if row.candidates else 0,
        "compared_weight_coverage": row.candidates[0].compared_weight_coverage if row.candidates else 0.0,
        "field_scores": _field_breakdown(row),
    }


def main() -> int:
    truth = _truth()
    rows = match_rows(
        SOURCE_PATH,
        TARGET_PATH,
        config=build_config(calibrated=True),
        group_code_column="集团码",
        max_target_rows=10_000,
    )

    matchable = [row for row in rows if truth[row.source_id]["预期是否可匹配"] == "Y"]
    no_match = [row for row in rows if truth[row.source_id]["预期是否可匹配"] == "N"]

    field_values: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        label = "matchable_correct_top1" if truth[row.source_id]["预期是否可匹配"] == "Y" else "true_no_match_top1"
        material_type = truth[row.source_id]["物料类型"]
        if not row.candidates:
            continue
        for field in row.candidates[0].field_scores:
            field_values[(material_type, label)][str(field["rule_id"])].append(float(field["score"]))

    aggregates: dict[str, object] = {}
    for (material_type, label), fields in sorted(field_values.items()):
        key = f"{material_type}:{label}"
        aggregates[key] = {
            rule_id: {
                "count": len(values),
                "mean_score_0_1": round(sum(values) / len(values), 4),
            }
            for rule_id, values in sorted(fields.items())
            if values
        }

    report = {
        "lowest_correct_top1": [
            _sample(row, truth[row.source_id])
            for row in sorted(matchable, key=lambda item: item.first_score)[:12]
        ],
        "highest_true_no_match_top1": [
            _sample(row, truth[row.source_id])
            for row in sorted(no_match, key=lambda item: item.first_score, reverse=True)[:12]
        ],
        "field_score_means": aggregates,
        "note": "These are calibrated scan scores. The samples diagnose absolute-score calibration; they are not vector-retrieval evidence.",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
