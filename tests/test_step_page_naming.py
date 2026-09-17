"""Static locks for the four-step business stage naming (UI 信息架构专项).

The web contract test (web/scripts/test-step-naming.mjs) runs inside the Vite
build; this pytest mirror keeps the same guarantees enforced on every
``pytest`` run even when the frontend job is skipped.
"""

from __future__ import annotations

import re
from pathlib import Path

WEB_SRC = Path(__file__).resolve().parents[1] / "web" / "src"

STEP_TITLES = (
    "第一步 · 数据上传",
    "第二步 · 进度监控",
    "第三步 · 人工调整",
    "第四步 · 输出结果",
)


def _read(relative: str) -> str:
    return (WEB_SRC / relative).read_text(encoding="utf-8")


def test_left_navigation_uses_the_four_business_stage_names() -> None:
    app = _read("App.vue")
    for title in STEP_TITLES:
        assert title in app, f"left navigation missing: {title}"


def test_each_step_page_shows_its_primary_stage_heading() -> None:
    assert "<h2>第一步 · 数据上传</h2>" in _read("views/ProfilesView.vue")
    assert "<h2>第二步 · 进度监控</h2>" in _read("views/TasksView.vue")
    assert "<h2>第三步 · 人工调整</h2>" in _read("views/ReviewView.vue")
    assert "<h2>第四步 · 输出结果</h2>" in _read("views/ResultsView.vue")


def test_scheme_configuration_is_a_sub_feature_of_step_one() -> None:
    profiles = _read("views/ProfilesView.vue")
    assert "匹配方案配置" in profiles
    assert "<h2>匹配方案</h2>" not in profiles
    assert "<h2>匹配方案配置</h2>" not in profiles
    workspace = _read("views/TaskWorkspaceBase.vue")
    assert "第一步 · 数据上传" in workspace
    assert "匹配方案配置" in workspace


def test_no_english_step_labels_in_business_pages() -> None:
    for page in (
        "views/ProfilesView.vue",
        "views/TasksView.vue",
        "views/ReviewView.vue",
        "views/ResultsView.vue",
    ):
        source = _read(page)
        assert not re.search(r"STEP\s*[1-4]", source), f"English step label leaked in {page}"
    assert "STEP 2 · 匹配计算" not in _read("views/TasksView.vue")


def test_step_one_actions_use_business_language() -> None:
    profiles = _read("views/ProfilesView.vue")
    assert "选择此方案并上传数据" in profiles
    assert "用此方案建任务" not in profiles
    assert "建任务" not in profiles
    tasks = _read("views/TasksView.vue")
    assert "返回第一步 · 数据上传" in tasks
    assert "前往 STEP 1" not in tasks
    workspace = _read("views/TaskWorkspaceBase.vue")
    assert "开始匹配 →" in workspace
    assert "保存并开始任务" not in workspace


def test_scheme_selection_still_enters_dual_excel_upload() -> None:
    profiles = _read("views/ProfilesView.vue")
    assert "path: '/tasks/new', query: { profile: row.profile_id }" in profiles
    workspace = _read("views/TaskWorkspaceBase.vue")
    assert "DualExcelUploadPanel" in workspace
    assert "已应用匹配方案" in workspace


def test_steps_two_to_four_consume_business_scheme_name() -> None:
    for page in ("views/TasksView.vue", "views/ReviewView.vue", "views/ResultsView.vue"):
        source = _read(page)
        assert "scheme_name" in source, f"{page} must render the backend scheme_name"
        assert "'未命名方案'" in source, f"{page} needs the neutral fallback for legacy runs"
