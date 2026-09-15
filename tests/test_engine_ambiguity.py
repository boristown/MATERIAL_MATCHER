from __future__ import annotations

from pathlib import Path

from material_matcher.domain.models import MatchingConfig
from material_matcher.matching.engine import match_rows


def _config(success: int = 60) -> MatchingConfig:
    return MatchingConfig.model_validate({
        "source_id_column": "编码",
        "scope_mode": "GLOBAL",
        "rules": [
            {"id": "name", "source": {"fields": ["名称"]}, "target": {"fields": ["名称"]}, "matcher": "exact", "weight": 70},
            {"id": "model", "source": {"fields": ["型号"]}, "target": {"fields": ["型号"]}, "matcher": "exact", "weight": 30},
        ],
        "retrieval": {"mode": "scan"},
        "decision": {"success_threshold": success, "review_enabled": True, "review_threshold": 20, "top_n": 5},
    })


def _write(tmp_path: Path, name: str, header: str, rows: list[str]) -> Path:
    path = tmp_path / name
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


def test_tie_between_different_group_codes_is_sent_to_review(tmp_path: Path) -> None:
    target = _write(tmp_path, "target.csv", "编码,集团码,名称,型号", [
        "T1,G1,电阻,R10", "T2,G2,电阻,R10",
    ])
    source = _write(tmp_path, "source.csv", "编码,名称,型号", ["0001,电阻,R10"])
    rows = match_rows(source, target, config=_config(), group_code_column="集团码", max_target_rows=1000)
    assert len(rows) == 1
    row = rows[0]
    assert row.status == "REVIEW"
    assert row.final_group_code is None
    assert row.first_score == row.second_score == 100.0
    assert {item.group_code for item in row.candidates} == {"G1", "G2"}


def test_tie_on_same_group_code_stays_auto_matched(tmp_path: Path) -> None:
    target = _write(tmp_path, "target.csv", "编码,集团码,名称,型号", [
        "T1,G1,电阻,R10", "T2,G1,电阻,R10",
    ])
    source = _write(tmp_path, "source.csv", "编码,名称,型号", ["0001,电阻,R10"])
    rows = match_rows(source, target, config=_config(), group_code_column="集团码", max_target_rows=1000)
    assert rows[0].status == "MATCHED"
    assert rows[0].final_group_code == "G1"


def test_dominant_candidate_still_auto_matched(tmp_path: Path) -> None:
    target = _write(tmp_path, "target.csv", "编码,集团码,名称,型号", [
        "T1,G1,电阻,R10", "T2,G2,电阻,R11",
    ])
    source = _write(tmp_path, "source.csv", "编码,名称,型号", ["0001,电阻,R10"])
    rows = match_rows(source, target, config=_config(), group_code_column="集团码", max_target_rows=1000)
    assert rows[0].status == "MATCHED"
    assert rows[0].final_group_code == "G1"
