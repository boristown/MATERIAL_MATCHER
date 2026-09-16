from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

from material_matcher.ingestion.reader import iter_tabular_rows


def _load_generator_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "generate_realistic_test_data.py"
    spec = importlib.util.spec_from_file_location("generate_realistic_test_data", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_GENERATOR = _load_generator_module()
generate_dataset = _GENERATOR.generate_dataset
generate_rows = _GENERATOR.generate_rows


def test_realistic_fixture_has_expected_business_distribution() -> None:
    sources, targets, truth, manifest = generate_rows()

    assert len(sources) == 1000
    assert len(targets) == 1200
    assert len(truth) == 1000
    assert manifest["expected_matched"] == 900
    assert manifest["expected_unmatched"] == 100
    assert manifest["match_ratio"] == 0.9
    assert manifest["source_type_distribution"] == {"Z001": 700, "Z006": 300}
    assert manifest["target_true_rows"] == 900
    assert manifest["target_distractor_rows"] == 300

    assert manifest["scenario_distribution"] == {
        "combined": 90,
        "exact": 270,
        "manufacturer_alias": 135,
        "missing_secondary": 90,
        "punctuation_space": 135,
        "standard_format": 135,
        "unit_variant": 45,
        "unmatched": 100,
    }

    target_codes = {row["集团码"] for row in targets}
    assert len(target_codes) == 1200

    matched_truth = [row for row in truth if row["预期是否可匹配"] == "Y"]
    unmatched_truth = [row for row in truth if row["预期是否可匹配"] == "N"]
    assert all(row["预期集团码"] in target_codes for row in matched_truth)
    assert all(row["预期集团码"] == "" for row in unmatched_truth)

    source_codes = {row["物料编码"] for row in sources}
    assert len(source_codes) == 1000
    assert all(len(code) == 18 and code.isdigit() for code in source_codes)

    # The fixture must exercise real dirty-data behavior rather than only exact copies.
    assert any(row["生产厂家"] in {"TI", "德州仪器", "ADI", "亚德诺", "泰科电子"} for row in sources)
    assert any(row["详细规范"] == "88" or row["总规范"] == "88" for row in sources)
    assert any(" x " in row["型号规格"] or "φ" in row["型号规格"] for row in sources)
    assert any(row["计量单位"] in {"PCS", "片", "支", "m2"} for row in sources)


def test_realistic_fixture_exports_workbooks_and_truth(tmp_path) -> None:
    paths = generate_dataset(tmp_path)

    source_rows = list(iter_tabular_rows(paths["source"]))
    target_rows = list(iter_tabular_rows(paths["target"]))
    assert len(source_rows) == 1000
    assert len(target_rows) == 1200
    assert source_rows[0]["物料编码"].isdigit()
    assert len(source_rows[0]["物料编码"]) == 18
    assert {row["物料类型"] for row in source_rows} == {"Z001", "Z006"}
    assert {row["物料类型"] for row in target_rows} == {"Z001", "Z006"}

    with paths["truth"].open("r", encoding="utf-8-sig", newline="") as stream:
        truth_rows = list(csv.DictReader(stream))
    assert len(truth_rows) == 1000
    assert sum(row["预期是否可匹配"] == "Y" for row in truth_rows) == 900
    assert sum(row["预期是否可匹配"] == "N" for row in truth_rows) == 100
