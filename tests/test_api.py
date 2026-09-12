from pathlib import Path

from fastapi.testclient import TestClient

from material_matcher.api import create_app
from material_matcher.settings import Settings


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        host="127.0.0.1",
        port=17843,
        admin_password="Ab3dEf7Gh9",
        config_dir=tmp_path / "etc",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "log",
        app_dir=tmp_path / "app",
        web_root=tmp_path / "web",
    )


def test_health_is_public(tmp_path: Path) -> None:
    client = TestClient(create_app(make_settings(tmp_path)))
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_admin_login_and_protected_system_info(tmp_path: Path) -> None:
    client = TestClient(create_app(make_settings(tmp_path)))

    bad = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert bad.status_code == 401

    login = client.post("/api/auth/login", json={"username": "admin", "password": "Ab3dEf7Gh9"})
    assert login.status_code == 200
    token = login.json()["token"]

    info = client.get("/api/system/info", headers={"Authorization": f"Bearer {token}"})
    assert info.status_code == 200
    assert info.json()["port"] == 17843
