from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from material_matcher.domain.models import MatchingConfig
from material_matcher.ingestion.reader import iter_tabular_rows
from material_matcher.matching.engine import RowResult, match_rows

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "realistic_materials" / "generated"
SOURCE_PATH = FIXTURE_DIR / "source_materials_1000.csv"
TARGET_PATH = FIXTURE_DIR / "target_group_codes_from_origin.csv"
TRUTH_PATH = FIXTURE_DIR / "ground_truth.csv"

SUCCESS_THRESHOLD = 88
REVIEW_THRESHOLD = 72
TOP_N = 10

NULLIFY = {
    "op": "nullify",
    "options": {
        "values": ["", "88", "<NULL>", "-", "/"],
        "case_sensitive": False,
    },
}


def _legacy_pipeline() -> list[dict[str, object]]:
    return [
        NULLIFY,
        {"op": "unicode_normalize", "options": {"form": "NFKC"}},
        {"op": "trim"},
        {"op": "case_map", "options": {"mode": "upper"}},
        {"op": "whitespace_map", "options": {"replacement": " "}},
    ]


def _pipeline(kind: str, *, calibrated: bool) -> list[dict[str, object]]:
    if not calibrated:
        return _legacy_pipeline()
    op = {
        "text": "text_normalize",
        "model": "model_normalize",
        "spec": "specification_normalize",
        "standard": "standard_number_normalize",
        "manufacturer": "manufacturer_normalize",
    }[kind]
    options: dict[str, object] = {}
    if kind == "text":
        options = {"compact": True}
    return [NULLIFY, {"op": op, "options": options}]


def _side(fields: list[str], kind: str, *, calibrated: bool, combine: str = "concat") -> dict[str, object]:
    return {
        "fields": fields,
        "combine": combine,
        "separator": " ",
        "pipeline": _pipeline(kind, calibrated=calibrated),
    }


def build_config(*, calibrated: bool) -> MatchingConfig:
    def hybrid_options(kind: str) -> dict[str, object]:
        if not calibrated:
            return {}
        contains_score = {
            "category": 0.82,
            "name": 0.84,
            "model": 0.70,
            "spec": 0.68,
            "package": 0.78,
            "manufacturer": 0.82,
            "standard": 0.76,
        }[kind]
        return {
            "contains_score": contains_score,
            "contains_length_sensitive": True,
        }

    rules: list[dict[str, object]] = [
        {
            "id": "category_path",
            "source": _side(
                ["二层分类描述", "三层分类描述", "四层分类描述", "五层分类描述"],
                "text",
                calibrated=calibrated,
            ),
            "target": _side(
                ["二层分类", "三层分类", "四层分类", "五层分类"],
                "text",
                calibrated=calibrated,
            ),
            "matcher": "hybrid",
            "matcher_options": hybrid_options("category"),
            "weight": 8,
        },
        {
            "id": "material_name",
            "source": _side(["物料名称"], "text", calibrated=calibrated),
            "target": _side(["物料名称"], "text", calibrated=calibrated),
            "matcher": "hybrid",
            "matcher_options": hybrid_options("name"),
            "weight": 12,
        },
        {
            "id": "model_identity",
            "source": _side(
                ["型号", "型号(牌号)"],
                "model",
                calibrated=calibrated,
                combine="best_of",
            ),
            "target": _side(
                ["型号", "牌号"],
                "model",
                calibrated=calibrated,
                combine="best_of",
            ),
            "matcher": "hybrid",
            "matcher_options": hybrid_options("model"),
            "weight": 28,
        },
        {
            "id": "specification",
            "source": _side(
                ["型号规格", "规格", "外形尺寸"],
                "spec",
                calibrated=calibrated,
                combine="best_of",
            ),
            "target": _side(
                ["型号规格", "规格", "外形尺寸"],
                "spec",
                calibrated=calibrated,
                combine="best_of",
            ),
            "matcher": "hybrid",
            "matcher_options": hybrid_options("spec"),
            "weight": 22,
        },
        {
            "id": "package",
            "source": _side(["封装形式"], "text", calibrated=calibrated),
            "target": _side(["封装形式"], "text", calibrated=calibrated),
            "matcher": "hybrid",
            "matcher_options": hybrid_options("package"),
            "weight": 8,
        },
        {
            "id": "manufacturer",
            "source": _side(["生产厂家"], "manufacturer", calibrated=calibrated),
            "target": _side(["生产厂家"], "manufacturer", calibrated=calibrated),
            "matcher": "hybrid",
            "matcher_options": hybrid_options("manufacturer"),
            "weight": 8,
        },
        {
            "id": "standard",
            "source": _side(
                ["总规范", "详细规范", "采购标准", "技术标准", "标准号"],
                "standard",
                calibrated=calibrated,
                combine="best_of",
            ),
            "target": _side(
                ["采用标准", "通用规范", "详细规范"],
                "standard",
                calibrated=calibrated,
                combine="best_of",
            ),
            "matcher": "hybrid",
            "matcher_options": hybrid_options("standard"),
            "weight": 10,
        },
        {
            "id": "quality_grade",
            "source": _side(["质量等级"], "text", calibrated=calibrated),
            "target": _side(["质量等级"], "text", calibrated=calibrated),
            "matcher": "exact",
            "weight": 4,
        },
    ]
    document: dict[str, object] = {
        "source_id_column": "物料编码",
        "scope_mode": "STRICT",
        "scope": {"source_field": "物料类型", "target_field": "物料类型"},
        "rules": rules,
        "decision": {
            "success_threshold": SUCCESS_THRESHOLD,
            "review_enabled": True,
            "review_threshold": REVIEW_THRESHOLD,
            "top_n": TOP_N,
        },
        "retrieval": {"mode": "scan", "retrieval_top_k": 200},
    }
    if calibrated:
        document["advanced"] = {
            "matching_safety": {
                "minimum_compared_field_count": 3,
                "minimum_compared_weight_coverage": 0.50,
                "minimum_score_gap": 3.0,
            }
        }
    return MatchingConfig.model_validate(document)


def _truth_rows() -> list[dict[str, str]]:
    with TRUTH_PATH.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _quantile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 4)
    weight = position - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 4)


def _distribution(values: Iterable[float]) -> dict[str, object]:
    data = [float(value) for value in values]
    if not data:
        return {"count": 0}
    histogram: dict[str, int] = {}
    edges = [0, 20, 40, 60, 70, 80, 88, 95, 100.000001]
    for left, right in zip(edges, edges[1:]):
        label = f"{left:g}-{min(right, 100):g}"
        histogram[label] = sum(left <= value < right for value in data)
    return {
        "count": len(data),
        "min": round(min(data), 4),
        "p10": _quantile(data, 0.10),
        "p25": _quantile(data, 0.25),
        "median": _quantile(data, 0.50),
        "p75": _quantile(data, 0.75),
        "p90": _quantile(data, 0.90),
        "p95": _quantile(data, 0.95),
        "max": round(max(data), 4),
        "mean": round(statistics.fmean(data), 4),
        "histogram": histogram,
    }


def _row_map(rows: list[RowResult]) -> dict[str, RowResult]:
    return {row.source_id: row for row in rows}


def _candidate_codes(row: RowResult, k: int) -> list[str]:
    return [candidate.group_code for candidate in row.candidates[:k]]


def _subset_metrics(
    truth_rows: list[dict[str, str]],
    rows_by_id: dict[str, RowResult],
) -> dict[str, object]:
    matchable = [row for row in truth_rows if row["预期是否可匹配"] == "Y"]
    unmatchable = [row for row in truth_rows if row["预期是否可匹配"] == "N"]
    output_rows = [rows_by_id[row["物料编码"]] for row in truth_rows]

    recall: dict[str, float] = {}
    for k in (1, 3, 5, 10):
        hits = sum(
            row["预期集团码"] in _candidate_codes(rows_by_id[row["物料编码"]], k)
            for row in matchable
        )
        recall[f"recall_at_{k}"] = round(hits / len(matchable), 6) if matchable else 0.0

    top1_correct = [
        row
        for row in matchable
        if rows_by_id[row["物料编码"]].candidates
        and rows_by_id[row["物料编码"]].candidates[0].group_code == row["预期集团码"]
    ]
    auto_rows = [row for row in truth_rows if rows_by_id[row["物料编码"]].status == "MATCHED"]
    auto_correct = [
        row
        for row in auto_rows
        if row["预期是否可匹配"] == "Y"
        and rows_by_id[row["物料编码"]].candidates
        and rows_by_id[row["物料编码"]].candidates[0].group_code == row["预期集团码"]
    ]
    false_auto_no_match = [
        row for row in unmatchable if rows_by_id[row["物料编码"]].status == "MATCHED"
    ]

    correct_top1_scores = [rows_by_id[row["物料编码"]].first_score for row in top1_correct]
    wrong_top1_scores: list[float] = []
    for truth in truth_rows:
        result = rows_by_id[truth["物料编码"]]
        if not result.candidates:
            continue
        if truth["预期是否可匹配"] == "N" or result.candidates[0].group_code != truth["预期集团码"]:
            wrong_top1_scores.append(result.first_score)

    return {
        "rows": len(truth_rows),
        "matchable_rows": len(matchable),
        "unmatchable_rows": len(unmatchable),
        "candidate": recall,
        "top1_accuracy": round(len(top1_correct) / len(matchable), 6) if matchable else 0.0,
        "auto_matched": len(auto_rows),
        "auto_match_precision": round(len(auto_correct) / len(auto_rows), 6) if auto_rows else None,
        "review_rows": sum(result.status == "REVIEW" for result in output_rows),
        "review_ratio": round(sum(result.status == "REVIEW" for result in output_rows) / len(output_rows), 6) if output_rows else 0.0,
        "unmatched_rows": sum(result.status == "UNMATCHED" for result in output_rows),
        "true_no_match_false_auto_matches": len(false_auto_no_match),
        "true_no_match_false_match_rate": round(len(false_auto_no_match) / len(unmatchable), 6) if unmatchable else 0.0,
        "status_counts": dict(Counter(result.status for result in output_rows)),
        "correct_top1_score_distribution": _distribution(correct_top1_scores),
        "wrong_top1_score_distribution": _distribution(wrong_top1_scores),
        "top1_top2_gap_distribution": _distribution(result.score_gap for result in output_rows),
    }


def evaluate(rows: list[RowResult], truth_rows: list[dict[str, str]]) -> dict[str, object]:
    by_id = _row_map(rows)
    missing = [row["物料编码"] for row in truth_rows if row["物料编码"] not in by_id]
    if missing:
        raise RuntimeError(f"matcher omitted {len(missing)} truth rows; first={missing[:3]}")
    overall = _subset_metrics(truth_rows, by_id)
    by_type = {
        material_type: _subset_metrics(
            [row for row in truth_rows if row["物料类型"] == material_type],
            by_id,
        )
        for material_type in sorted({row["物料类型"] for row in truth_rows})
    }
    by_scenario = {
        scenario: _subset_metrics(
            [row for row in truth_rows if row["场景"] == scenario],
            by_id,
        )
        for scenario in sorted({row["场景"] for row in truth_rows})
    }
    return {"overall": overall, "by_material_type": by_type, "by_scenario": by_scenario}


def _failure_attribution(
    truth_rows: list[dict[str, str]],
    target_rows: list[dict[str, object]],
    baseline: list[RowResult],
    calibrated: list[RowResult],
) -> dict[str, object]:
    baseline_by_id = _row_map(baseline)
    calibrated_by_id = _row_map(calibrated)
    targets_by_code: dict[str, list[dict[str, object]]] = defaultdict(list)
    for target in target_rows:
        targets_by_code[str(target.get("集团码") or "")].append(target)

    counts = Counter()
    samples: dict[str, list[dict[str, object]]] = defaultdict(list)
    for truth in truth_rows:
        source_id = truth["物料编码"]
        if truth["预期是否可匹配"] == "N":
            counts["data_intrinsically_unmatchable"] += 1
            continue
        expected = truth["预期集团码"]
        target_matches = targets_by_code.get(expected, [])
        if not target_matches:
            category = "field_mapping_failure"
        elif not any(str(target.get("物料类型") or "") == truth["物料类型"] for target in target_matches):
            category = "field_mapping_failure"
        else:
            result = calibrated_by_id[source_id]
            candidate_codes = _candidate_codes(result, TOP_N)
            if expected not in candidate_codes:
                # Scan evaluates every in-scope target before TopN truncation. If the
                # correct code misses TopN here, it is reranking/scoring, not retrieval.
                category = "rerank_failure"
            elif result.candidates and result.candidates[0].group_code != expected:
                category = "rerank_failure"
            else:
                baseline_result = baseline_by_id[source_id]
                baseline_correct = bool(
                    baseline_result.candidates
                    and baseline_result.candidates[0].group_code == expected
                )
                if not baseline_correct and truth["场景"] in {
                    "space_punctuation",
                    "standard_format",
                    "combined",
                }:
                    category = "normalization_failure_fixed"
                else:
                    category = "correct_after_calibration"
        counts[category] += 1
        if len(samples[category]) < 12:
            before = baseline_by_id[source_id]
            after = calibrated_by_id[source_id]
            samples[category].append(
                {
                    "material_code": source_id,
                    "material_type": truth["物料类型"],
                    "scenario": truth["场景"],
                    "expected_group_code": expected,
                    "baseline_top1": before.candidates[0].group_code if before.candidates else None,
                    "baseline_score": before.first_score,
                    "calibrated_top1": after.candidates[0].group_code if after.candidates else None,
                    "calibrated_score": after.first_score,
                    "calibrated_top10": _candidate_codes(after, TOP_N),
                }
            )

    counts["scan_retrieval_failure"] = 0
    return {
        "counts": dict(counts),
        "samples": dict(samples),
        "scan_note": "scan mode scores every in-scope target; missing the correct code from Top10 is attributed to reranking/scoring, not candidate retrieval.",
        "vector_note": "NOT_EVALUATED: CI does not load the production BAAI/bge-base-zh-v1.5 model, so no formal vector Recall claim is made.",
    }


def run() -> dict[str, object]:
    truth_rows = _truth_rows()
    target_rows = list(iter_tabular_rows(TARGET_PATH))
    if len(truth_rows) != 1000:
        raise RuntimeError(f"expected 1000 truth rows, found {len(truth_rows)}")
    if sum(row["预期是否可匹配"] == "Y" for row in truth_rows) != 900:
        raise RuntimeError("fixture must contain 900 matchable rows")
    if sum(row["预期是否可匹配"] == "N" for row in truth_rows) != 100:
        raise RuntimeError("fixture must contain 100 true NO_MATCH rows")

    baseline_config = build_config(calibrated=False)
    calibrated_config = build_config(calibrated=True)
    baseline_rows = match_rows(
        SOURCE_PATH,
        TARGET_PATH,
        config=baseline_config,
        group_code_column="集团码",
        max_target_rows=10_000,
    )
    calibrated_rows = match_rows(
        SOURCE_PATH,
        TARGET_PATH,
        config=calibrated_config,
        group_code_column="集团码",
        max_target_rows=10_000,
    )

    baseline_metrics = evaluate(baseline_rows, truth_rows)
    calibrated_metrics = evaluate(calibrated_rows, truth_rows)
    return {
        "fixture": {
            "source_rows": len(truth_rows),
            "target_rows": len(target_rows),
            "matchable": 900,
            "true_no_match": 100,
            "types": dict(Counter(row["物料类型"] for row in truth_rows)),
        },
        "thresholds": {
            "success": SUCCESS_THRESHOLD,
            "review": REVIEW_THRESHOLD,
            "top_n": TOP_N,
            "unchanged_between_baseline_and_calibrated": True,
        },
        "baseline": baseline_metrics,
        "calibrated": calibrated_metrics,
        "failure_attribution": _failure_attribution(
            truth_rows,
            target_rows,
            baseline_rows,
            calibrated_rows,
        ),
        "acceptance_scope": {
            "scan": "evaluated",
            "vector": "not formally evaluated in CI because the real production BGE model is not loaded",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate matching quality on the origin_data.zip-derived 1000-row fixture")
    parser.add_argument("--output", type=Path, help="optional JSON output path")
    args = parser.parse_args()
    report = run()
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(encoded)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
