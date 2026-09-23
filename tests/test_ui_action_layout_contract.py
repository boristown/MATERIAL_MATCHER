"""Static UI action/header layout contract for Issue #166.

Mirrors the Node contract in the frontend build so backend-only pytest runs
also catch spacing regressions such as flex gap plus Element Plus sibling
margins.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def _read(relative: str) -> str:
    return (WEB / relative).read_text(encoding="utf-8")


def test_shared_header_and_action_group_contract() -> None:
    css = _read("src/styles.css")

    assert re.search(r"\.toolbar\s*\{[^}]*align-items:\s*flex-start[^}]*gap:\s*16px", css)
    assert re.search(r"\.section-head\s*\{[^}]*gap:\s*16px", css)
    assert re.search(r"\.actions\s*\{[^}]*justify-content:\s*flex-start[^}]*gap:\s*10px", css)
    assert ".actions .el-button, .toolbar-actions .el-button, .quick .el-button { margin-left: 0; }" in css
    assert ".actions .el-button + .el-button, .toolbar-actions .el-button + .el-button, .quick .el-button + .el-button { margin-left: 0; }" in css
    assert re.search(r"\.workspace-toolbar\s*\{[^}]*justify-content:\s*flex-start[^}]*gap:\s*24px", css)
    assert re.search(
        r"@media \(max-width: 760px\)[\s\S]*?\.toolbar-actions\s*\{[^}]*justify-content:\s*flex-start[^}]*width:\s*100%",
        css,
    )


def test_review_action_groups_use_gap_without_element_plus_margin() -> None:
    css = _read("src/styles/pages/review.css")

    for selector in (
        ".review-page .review-toolbar-actions .el-button",
        ".review-page .review-empty-actions .el-button",
        ".review-page .review-threshold-actions .el-button",
        ".review-page .review-field-actions .el-button",
        ".review-page .review-record-actions > div:last-child .el-button",
    ):
        assert selector in css

    assert re.search(r"\.review-page \.review-empty-actions\s*\{[^}]*gap:\s*10px", css)
    assert ".review-empty-actions .el-button + .el-button { margin-left: 10px; }" not in css
    assert re.search(
        r"@media \(max-width: 820px\)[\s\S]*?\.review-page \.review-threshold-actions\s*\{[^}]*justify-content:\s*flex-start",
        css,
    )


def test_page_specific_alignment_and_canvas_gutter() -> None:
    results = _read("src/styles/pages/results.css")
    system = _read("src/styles/pages/system.css")
    canvas = _read("src/components/FieldMappingCanvas.vue")
    workspace = _read("src/views/TaskWorkspace.vue")

    assert re.search(r"\.results-toolbar\s*\{[^}]*align-items:\s*flex-start", results)
    assert re.search(r"\.system-toolbar\s*\{[^}]*align-items:\s*flex-start", system)
    assert re.search(r"\.mapping-view-tools\s*\{[\s\S]*?padding:\s*0 6px;", canvas)
    assert ".threshold-row :deep(.el-button), .section-title-row :deep(.el-button) { margin-left: 0; }" in workspace
