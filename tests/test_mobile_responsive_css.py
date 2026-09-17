"""Locks: mobile shell adaptation exists and the desktop layout rules stay untouched."""

from __future__ import annotations

import re
from pathlib import Path

CSS = (Path(__file__).resolve().parents[1] / "web" / "src" / "styles.css").read_text(encoding="utf-8")
MARKER = "/* ===== 手机端适配（≤760px）"


def _split() -> tuple[str, str]:
    index = CSS.index(MARKER)
    return CSS[:index], CSS[index:]


def test_desktop_shell_rules_are_untouched() -> None:
    base, _ = _split()
    assert re.search(r"aside\s*{[^}]*width: 224px", base)
    assert re.search(r"aside\s*{[^}]*position: fixed", base)
    assert "main { margin-left: 224px;" in base
    assert ".content { padding: 22px 24px 40px; max-width: 1480px; }" in base
    assert ".shell { display: flex; min-height: 100vh; min-height: 100dvh; }" in base


def test_mobile_block_is_media_scoped() -> None:
    _, mobile = _split()
    assert "@media (max-width: 760px) {" in mobile
    assert "100vh" not in mobile


def test_mobile_shell_flips_sidebar_to_top_nav() -> None:
    _, mobile = _split()
    for token in (
        ".shell { display: block; }",
        "position: static",
        "main { margin-left: 0; }",
        ".step-nav { flex-direction: row; overflow-x: auto",
        ".step-nav .nav-desc { display: none; }",
        ".support-nav { display: flex; flex-direction: row",
    ):
        assert token in mobile, f"missing mobile rule: {token}"


def test_mobile_overlays_and_forms_are_capped() -> None:
    _, mobile = _split()
    assert ".content .el-input, .content .el-select, .content .el-slider, .content .el-input-number { max-width: 100%; }" in mobile
    assert ".el-overlay-dialog .el-dialog { max-width: calc(100vw - 20px); }" in mobile
    assert ".el-message-box { max-width: calc(100vw - 32px); }" in mobile
    assert ".el-drawer { max-width: 100vw; }" in mobile
    assert ".uploads { grid-template-columns: 1fr" in mobile


def test_step3_console_escapes_320px_overflow() -> None:
    review = (Path(__file__).resolve().parents[1] / "web" / "src" / "styles" / "pages" / "review.css").read_text(encoding="utf-8")
    assert re.search(r"@media \(max-width: 480px\)[\s\S]*?\.review-console-main\s*{[^}]*min-width: 0", review)
