from __future__ import annotations

import json
from pathlib import Path

import pytest

from material_matcher.services.export_profile import (
    DEFAULT_EXPORT_PROFILE_DOCUMENT,
    EXPORT_PROFILE_FILENAME,
    default_export_profile,
    load_export_profile,
)


def test_default_export_profile_preserves_current_business_workbook_contract() -> None:
    profile = default_export_profile()

    assert profile.sheet("summary") == "匹配摘要"
    assert profile.sheet("final_result") == "最终匹配结果"
    assert profile.sheet("top_candidates") == "Top5候选"
    assert profile.sheet("audit") == "人工操作记录"
    assert profile.sheet("unmatched") == "未匹配清单"
    assert profile.candidate_top_n == 5
    assert profile.header("status") == "匹配状态"
    assert profile.header("final_group_code") == "最终集团码"
    assert profile.header("similarity") == "相似度"
    assert profile.status_label("MATCHED") == "自动匹配"
    assert profile.status_label("CONFIRMED") == "人工匹配"
    assert profile.status_label("REVIEW") == "待处理"
    assert profile.status_label("UNMATCHED") == "未匹配"
    assert profile.color("header_fill") == "1F4E78"
    assert profile.color("exact_fill") == "E2F0D9"
    assert profile.color("partial_fill") == "FFF2CC"
    assert profile.color("different_fill") == "FCE4D6"
    assert profile.color("missing_fill") == "E7E6E6"
    assert profile.freeze_panes == "A3"
    assert profile.summary_column_widths == {"A": 22.0, "B": 34.0, "C": 22.0, "D": 34.0}


def test_export_profile_supports_safe_partial_local_override(tmp_path: Path) -> None:
    config_dir = tmp_path / "etc"
    config_dir.mkdir(parents=True)
    (config_dir / EXPORT_PROFILE_FILENAME).write_text(
        json.dumps(
            {
                "display_name": "内网客户正式模板",
                "candidate_top_n": 3,
                "sheets": {"final_result": "正式结果"},
                "headers": {"final_group_code": "集团物料编码"},
                "labels": {"status": {"CONFIRMED": "人工确认"}},
                "style": {
                    "max_column_width": 42,
                    "summary_column_widths": {"B": 40},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    profile = load_export_profile(config_dir, strict=True)

    assert profile.source_path == config_dir / EXPORT_PROFILE_FILENAME
    assert profile.sheet("summary") == "匹配摘要"
    assert profile.sheet("final_result") == "正式结果"
    assert profile.candidate_top_n == 3
    assert profile.header("final_group_code") == "集团物料编码"
    assert profile.status_label("MATCHED") == "自动匹配"
    assert profile.status_label("CONFIRMED") == "人工确认"
    assert profile.max_column_width == 42
    assert profile.summary_column_widths["A"] == 22.0
    assert profile.summary_column_widths["B"] == 40.0


def test_invalid_local_export_profile_falls_back_without_breaking_export(tmp_path: Path) -> None:
    config_dir = tmp_path / "etc"
    config_dir.mkdir(parents=True)
    (config_dir / EXPORT_PROFILE_FILENAME).write_text(
        json.dumps({"sheets": {"summary": "X" * 32}}, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.warns(RuntimeWarning, match="继续使用内置标准导出模板"):
        profile = load_export_profile(config_dir)

    assert profile.source_path is None
    assert profile.sheet("summary") == "匹配摘要"


def test_invalid_local_export_profile_can_be_validated_strictly(tmp_path: Path) -> None:
    config_dir = tmp_path / "etc"
    config_dir.mkdir(parents=True)
    (config_dir / EXPORT_PROFILE_FILENAME).write_text(
        json.dumps({"unknown_option": True}, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="未知导出模板配置项"):
        load_export_profile(config_dir, strict=True)


def test_repository_example_matches_built_in_standard_profile() -> None:
    root = Path(__file__).resolve().parents[1]
    example = json.loads((root / "config" / "examples" / "export_profile.json").read_text(encoding="utf-8"))

    assert example == DEFAULT_EXPORT_PROFILE_DOCUMENT
