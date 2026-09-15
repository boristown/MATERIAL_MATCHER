from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from material_matcher.api.app import create_app
from material_matcher.api.frontend import attach_frontend
from material_matcher.settings import Settings


def test_frontend_spa_is_served_without_shadowing_api(tmp_path: Path) -> None:
    dist = tmp_path / "web" / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<html><body>material matcher spa</body></html>", encoding="utf-8")
    (assets / "app.js").write_text("console.log('ok')", encoding="utf-8")
    settings = Settings(
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "etc",
        log_dir=tmp_path / "log",
        admin_password="Ab3dEf7Gh9",
        worker_enabled=False,
        web_dist_dir=dist,
    )
    app = create_app(settings)
    attach_frontend(app, settings.web_dist_dir)

    with TestClient(app) as client:
        root = client.get("/")
        assert root.status_code == 200
        assert "material matcher spa" in root.text

        route = client.get("/tasks/new")
        assert route.status_code == 200
        assert "material matcher spa" in route.text

        asset = client.get("/assets/app.js")
        assert asset.status_code == 200
        assert "console.log" in asset.text

        missing_api = client.get("/api/does-not-exist")
        assert missing_api.status_code in {401, 404}
        assert "material matcher spa" not in missing_api.text


def test_missing_frontend_dist_returns_404(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "etc",
        log_dir=tmp_path / "log",
        admin_password="Ab3dEf7Gh9",
        worker_enabled=False,
        web_dist_dir=tmp_path / "missing-dist",
    )
    app = create_app(settings)
    attach_frontend(app, settings.web_dist_dir)
    with TestClient(app) as client:
        assert client.get("/").status_code == 404
