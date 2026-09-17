from __future__ import annotations

from pathlib import Path
import tomllib

from fastapi.testclient import TestClient

from material_matcher import __version__


def test_pyproject_is_runtime_version_source() -> None:
    root = Path(__file__).resolve().parents[1]
    with (root / "pyproject.toml").open("rb") as stream:
        project_version = str(tomllib.load(stream)["project"]["version"])
    assert __version__ == project_version
    init_text = (root / "src/material_matcher/__init__.py").read_text(encoding="utf-8")
    assert project_version not in init_text
    assert "get_version" in init_text


def test_health_and_about_report_runtime_version(client: TestClient, authed: TestClient, monkeypatch) -> None:
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["version"] == __version__

    assert client.get("/api/about").status_code == 401
    monkeypatch.setenv("MATERIAL_MATCHER_BUILD_TIME", "2026-09-17T06:00:00+00:00")
    monkeypatch.setenv("MATERIAL_MATCHER_GIT_COMMIT", "abcdef123456")
    monkeypatch.setenv("MATERIAL_MATCHER_DEPLOYMENT_MODE", "docker-source")
    about = authed.get("/api/about")
    assert about.status_code == 200
    payload = about.json()
    assert payload["product_name"] == "物料集团码智能匹配平台"
    assert payload["version"] == __version__
    assert payload["build_time"] == "2026-09-17T06:00:00+00:00"
    assert payload["git_commit"] == "abcdef123456"
    assert payload["deployment_mode"] == "docker-source"


def test_frontend_does_not_hardcode_legacy_version() -> None:
    root = Path(__file__).resolve().parents[1]
    app = (root / "web/src/App.vue").read_text(encoding="utf-8")
    assert "v1.0" not in app
    assert "api.get('/health')" in app
    assert "runtimeVersion" in app
    about = (root / "web/src/views/AboutView.vue").read_text(encoding="utf-8")
    assert "api.get('/about')" in about
    assert "原生源码部署" in about
    assert "Docker 源码部署" in about


def test_docker_source_uses_host_bind_mounts() -> None:
    root = Path(__file__).resolve().parents[1]
    compose = (root / "docker/compose.yaml").read_text(encoding="utf-8")
    assert "${MM_DATA_DIR:-./data}:/data" in compose
    assert "${MM_CONFIG_DIR:-./config}:/config" in compose
    assert "${MM_LOG_DIR:-./logs}:/logs" in compose
    assert "../src:/app/src:ro" in compose
    assert "../web:/app/web-source:ro" in compose
    assert "MATERIAL_MATCHER_DEPLOYMENT_MODE: docker-source" in compose
    assert "\nvolumes:\n" not in compose  # no top-level named/anonymous persistence volume


def test_native_installer_keeps_data_protection_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    installer = (root / "installer/install.sh").read_text(encoding="utf-8")
    for marker in (
        "storage.env is the single source of truth",
        "同时检测到两份 metadata DB",
        "新版本部署前诊断失败，旧服务保持不变",
        "rollback_activation",
        "source/src",
        "web-dist",
    ):
        assert marker in installer
    assert "rm -rf \"$DATA_DIR\"" not in installer


def test_maintenance_sources_cover_required_operations() -> None:
    root = Path(__file__).resolve().parents[1]
    ctl = (root / "tools/mmctl.sh").read_text(encoding="utf-8")
    for command in (
        "status", "start", "stop", "restart", "logs", "doctor",
        "diagnostics", "backup", "restore", "rebuild-frontend", "version",
    ):
        assert command in ctl
    rebuild = (root / "tools/rebuild_frontend.sh").read_text(encoding="utf-8")
    assert "npm ci --offline" in rebuild
    assert "BACKUP_DIST" in rebuild
    assert "rollback" in rebuild
    assert "/api/health" in rebuild
