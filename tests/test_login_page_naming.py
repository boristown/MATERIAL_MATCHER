"""Static locks for the login page branding + mobile responsive special (UI 专项).

Mirrors web/scripts/test-login-brand.mjs so the guarantees hold on every
backend pytest run even when the frontend job is skipped.
"""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"

VIEW = (WEB / "src" / "views" / "LoginView.vue").read_text(encoding="utf-8")
CSS = (WEB / "src" / "styles.css").read_text(encoding="utf-8")
HTML = (WEB / "index.html").read_text(encoding="utf-8")


def test_product_name_is_the_platform_not_the_engine() -> None:
    assert "物料集团码匹配引擎" not in VIEW
    assert "物料集团码" in VIEW and "智能匹配平台" in VIEW
    assert "使用分配的本地账号登录" in VIEW
    assert "匹配引擎" not in HTML


def test_login_shows_xiaogang_ai_brand_using_existing_asset() -> None:
    assert "/favicon.svg" in VIEW
    assert "小罡 AI" in VIEW


def test_login_version_comes_from_the_backend() -> None:
    assert "api.get('/health')" in VIEW
    assert not re.search(r"v1\.0[^-9.]", VIEW)


def test_login_layout_is_mobile_first() -> None:
    assert "min-height: 100vh" in CSS
    assert "min-height: 100dvh" in CSS
    assert "overflow-y: auto" in CSS
    assert "env(safe-area-inset-top)" in CSS
    assert "env(safe-area-inset-bottom)" in CSS
    assert "width: 420px" not in CSS
    assert re.search(r"\.login-stage\s*{[^}]*margin:\s*auto", CSS)
    assert "max-width: 440px" in CSS
    assert "clamp(28px, 4.6vw, 36px)" in CSS
    assert "@media (max-width: 480px)" in CSS


def test_login_touch_targets_avoid_ios_zoom() -> None:
    assert re.search(r"\.login \.card \.el-input__inner { font-size: 16px", CSS)
    assert "min-height: 50px" in CSS
    assert re.search(r"\.login \.card \.el-button--primary { width: 100%; height: 50px", CSS)


def test_authentication_contract_is_untouched() -> None:
    for token in (
        "api.post('/auth/login'",
        "api.post('/auth/change-password'",
        "must_change_password",
        "consumeAuthReturnTo",
        "consumeAuthExpiredNotice",
    ):
        assert token in VIEW, f"auth contract token missing: {token}"
