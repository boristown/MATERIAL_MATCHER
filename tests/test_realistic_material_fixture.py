from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

from material_matcher.ingestion.reader import iter_tabular_rows

ROOT = Path(__file__).resolve().parents[1]
SEED_ZIP = ROOT / "origin_data.zip"


def _load_generator_module():
    script_path = ROOT / "scripts" / "generate_realistic_test_data.py"
    spec = importlib.util.spec_from_file_location("generate_realistic_test_data", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_GENERATOR = _load_generator_module()
discover_seed_rows = _GENERATOR.discover_seed_rows
build_seed_pairs = _GENERATOR.build_seed_pairs
generate_dataset = _GENERATOR.generate_dataset
generate_rows = _GENERATOR.generate_rows


def test_origin_zip_is_the_real_fixture_source() -> None:
    assert SEED_ZIP.exists(), "origin_data.zip must stay versioned as the canonical public seed package"
    sources, targets, inventory = discover_seed_rows(SEED_ZIP)

    assert len(inventory["seed_files_scanned"]) >= 10
    assert inventory["source_seed_rows"] == len(sources) > 0
    assert inventory["target_seed_rows"] == len(targets) > 0
    assert inventory["source_seed_by_type"]["Z001"] > 0
    assert inventory["source_seed_by_type"]["Z006"] > 0
    assert inventory["target_seed_by_type"]["Z001"] > 0
    assert inventory["target_seed_by_type"]["Z006"] > 0
    assert len(inventory["seed_zip_sha256"]) == 64

    pairs = build_seed_pairs(sources, targets)
    assert any(pair.source.material_type == "Z001" for pair in pairs)
    assert any(pair.source.material_type == "Z006" for pair in pairs)
    assert all(pair.source.file_name and pair.target.file_name for pair in pairs)


def test_realistic_fixture_has_900_100_truth_and_traceability() -> None:
    sources, targets, truth, manifest = generate_rows(SEED_ZIP)

    assert len(sources) == 1000
    assert len(truth) == 1000
    assert len(targets) > 0
    assert manifest["generator"] == "origin_data.zip seed-driven"
    assert manifest["expected_matched"] == 900
    assert manifest["expected_unmatched"] == 100
    assert manifest["match_ratio"] == 0.9
    assert manifest["source_type_distribution"] == {"Z001": 700, "Z006": 300}
    assert manifest["high_confidence_seed_pairs"] > 0
    assert manifest["high_confidence_seed_pairs_by_type"]["Z001"] > 0
    assert manifest["high_confidence_seed_pairs_by_type"]["Z006"] > 0

    target_codes = {row["集团码"] for row in targets}
    matched_truth = [row for row in truth if row["预期是否可匹配"] == "Y"]
    unmatched_truth = [row for row in truth if row["预期是否可匹配"] == "N"]
    assert len(matched_truth) == 900
    assert len(unmatched_truth) == 100
    assert all(row["预期集团码"] in target_codes for row in matched_truth)
    assert all(row["预期集团码"] == "" for row in unmatched_truth)

    assert all(row["种子源文件"] and int(row["种子源行号"]) > 0 for row in truth)
    assert all(row["种子目标文件"] and int(row["种子目标行号"]) > 0 for row in truth)
    assert all(float(row["种子配对分"]) >= 0.74 for row in truth)

    source_codes = {row["物料编码"] for row in sources}
    assert len(source_codes) == 1000
    assert all(len(code) == 18 and code.isdigit() for code in source_codes)
    assert any(row["场景"] == "space_punctuation" for row in truth)
    assert any(row["场景"] == "missing_secondary" for row in truth)
    assert sum(row["场景"] == "unmatched_variant" for row in truth) == 100


def test_origin_seed_fixture_exports_workbooks_and_truth(tmp_path: Path) -> None:
    paths = generate_dataset(SEED_ZIP, tmp_path)

    source_rows = list(iter_tabular_rows(paths["source"]))
    target_rows = list(iter_tabular_rows(paths["target"]))
    assert len(source_rows) == 1000
    assert len(target_rows) > 0
    assert source_rows[0]["物料编码"].isdigit()
    assert len(source_rows[0]["物料编码"]) == 18
    assert {row["物料类型"] for row in source_rows} == {"Z001", "Z006"}
    assert {row["物料类型"] for row in target_rows} == {"Z001", "Z006"}

    with paths["truth"].open("r", encoding="utf-8-sig", newline="") as stream:
        truth_rows = list(csv.DictReader(stream))
    assert len(truth_rows) == 1000
    assert sum(row["预期是否可匹配"] == "Y" for row in truth_rows) == 900
    assert sum(row["预期是否可匹配"] == "N" for row in truth_rows) == 100

    manifest = paths["manifest"].read_text(encoding="utf-8")
    assert "origin_data.zip seed-driven" in manifest
    assert "seed_zip_sha256" in manifest
