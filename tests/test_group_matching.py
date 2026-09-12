from pathlib import Path

from openpyxl import Workbook

from material_matcher.matching import run_matching


def save_book(path: Path, headers: list[str], rows: list[list[object]]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "数据"
    ws.append(headers)
    for row in rows:
        ws.append(row)
    wb.save(path)


def base_config() -> dict:
    return {
        "source_sheet": "数据",
        "source_header_row": 1,
        "target_sheet": "数据",
        "target_header_row": 1,
        "source_id_column": "物料号",
        "group_code_column": "集团码",
        "mappings": [
            {"source_header": "名称", "target_header": "名称", "weight": 1.0, "method": "hybrid", "name": "名称"},
        ],
        "threshold": 0.80,
        "top_n": 5,
        "candidate_limit": 20,
    }


def test_strict_group_only_compares_same_group(tmp_path: Path) -> None:
    source = tmp_path / "source.xlsx"
    target = tmp_path / "target.xlsx"
    save_book(source, ["物料号", "物料组", "名称"], [["S1", "A", "同名物料"]])
    save_book(
        target,
        ["集团码", "集团组", "名称"],
        [["WRONG", "B", "同名物料"], ["RIGHT", "A", "同名物料"]],
    )
    config = base_config() | {
        "group_mode": "strict",
        "source_group_column": "物料组",
        "target_group_column": "集团组",
    }
    result = run_matching(source, target, config)
    assert result["rows"][0]["matched_group_code"] == "RIGHT"
    assert result["summary"]["group_mode"] == "strict"


def test_mapped_group_supports_one_source_to_multiple_target_groups(tmp_path: Path) -> None:
    source = tmp_path / "source.xlsx"
    target = tmp_path / "target.xlsx"
    save_book(source, ["物料号", "物料组", "名称"], [["S1", "SAP-A", "复合板"]])
    save_book(
        target,
        ["集团码", "集团组", "名称"],
        [["G1", "集团-X", "完全不同"], ["G2", "集团-Y", "复合板"], ["G3", "集团-Z", "复合板"]],
    )
    config = base_config() | {
        "group_mode": "mapped",
        "source_group_column": "物料组",
        "target_group_column": "集团组",
        "group_mapping": {"SAP-A": ["集团-X", "集团-Y"]},
    }
    result = run_matching(source, target, config)
    assert result["rows"][0]["matched_group_code"] == "G2"
    assert all(candidate["group_code"] != "G3" for candidate in result["rows"][0]["candidates"])


def test_global_group_ignores_group_values(tmp_path: Path) -> None:
    source = tmp_path / "source.xlsx"
    target = tmp_path / "target.xlsx"
    save_book(source, ["物料号", "物料组", "名称"], [["S1", "A", "唯一名称"]])
    save_book(target, ["集团码", "集团组", "名称"], [["G1", "B", "唯一名称"]])
    config = base_config() | {"group_mode": "global"}
    result = run_matching(source, target, config)
    assert result["rows"][0]["matched_group_code"] == "G1"
