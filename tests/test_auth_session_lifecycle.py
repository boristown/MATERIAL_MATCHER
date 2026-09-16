from __future__ import annotations

from pathlib import Path
import time

from fastapi.testclient import TestClient

from material_matcher.api.app import COOKIE_NAME, create_app
from material_matcher.settings import Settings
from material_matcher.storage.metadata import MetadataRepository

BOOTSTRAP_PASSWORD = "Bootstrap12345"
READY_ADMIN_PASSWORD = "ReadyAdmin12345"


def _settings(tmp_path: Path, *, ttl_seconds: int = 3600) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "etc",
        log_dir=tmp_path / "log",
        admin_password=BOOTSTRAP_PASSWORD,
        session_ttl_seconds=ttl_seconds,
        worker_enabled=False,
        embedding_model_root=tmp_path / "models",
        web_dist_dir=tmp_path / "web-dist",
    )


def _login(client: TestClient, username: str, password: str) -> tuple[str, dict[str, object]]:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    token = client.cookies.get(COOKIE_NAME)
    assert token
    return token, response.json()


def _ready_admin(client: TestClient) -> str:
    token, payload = _login(client, "admin", BOOTSTRAP_PASSWORD)
    if payload["user"]["must_change_password"]:
        changed = client.post(
            "/api/auth/change-password",
            json={"current_password": BOOTSTRAP_PASSWORD, "new_password": READY_ADMIN_PASSWORD},
        )
        assert changed.status_code == 200
        token, _ = _login(client, "admin", READY_ADMIN_PASSWORD)
    return token


def _assert_auth_required(response) -> None:
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_login_cookie_survives_app_recreation_with_same_metadata_db(tmp_path: Path) -> None:
    settings = _settings(tmp_path, ttl_seconds=1234)
    assert settings.metadata_db_path == settings.data_dir / "meta" / "material_matcher.db"

    with TestClient(create_app(settings)) as first:
        response = first.post(
            "/api/auth/login",
            json={"username": "admin", "password": BOOTSTRAP_PASSWORD},
        )
        assert response.status_code == 200
        token = first.cookies.get(COOKIE_NAME)
        assert token
        assert f"Max-Age={settings.session_ttl_seconds}" in response.headers["set-cookie"]
        assert first.get("/api/auth/me").status_code == 200

    with MetadataRepository(settings.metadata_db_path).connect() as connection:
        persisted = connection.execute(
            "SELECT username,expires_at FROM sessions WHERE token=?",
            (token,),
        ).fetchone()
    assert persisted is not None
    assert persisted["username"] == "admin"
    assert float(persisted["expires_at"]) > time.time()

    # Simulate a normal service restart: a brand-new FastAPI app opens the same metadata DB.
    with TestClient(create_app(settings)) as restarted:
        restarted.cookies.set(COOKIE_NAME, token)
        me = restarted.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json()["username"] == "admin"


def test_expired_session_is_rejected_after_app_recreation(tmp_path: Path) -> None:
    settings = _settings(tmp_path, ttl_seconds=5)
    with TestClient(create_app(settings)) as first:
        token, _ = _login(first, "admin", BOOTSTRAP_PASSWORD)

    with MetadataRepository(settings.metadata_db_path).connect() as connection:
        connection.execute(
            "UPDATE sessions SET expires_at=? WHERE token=?",
            (time.time() - 1, token),
        )

    with TestClient(create_app(settings)) as restarted:
        restarted.cookies.set(COOKIE_NAME, token)
        _assert_auth_required(restarted.get("/api/auth/me"))

    with MetadataRepository(settings.metadata_db_path).connect() as connection:
        assert connection.execute("SELECT token FROM sessions WHERE token=?", (token,)).fetchone() is None


def test_disabled_account_invalidates_existing_session(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        admin_token = _ready_admin(client)
        created = client.post(
            "/api/users",
            json={"username": "disabled-user", "password": "Disabled12345", "role": "viewer"},
        )
        assert created.status_code == 200

        user_token, _ = _login(client, "disabled-user", "Disabled12345")
        assert client.get("/api/auth/me").status_code == 200

        client.cookies.set(COOKIE_NAME, admin_token)
        disabled = client.patch("/api/users/disabled-user", json={"enabled": False})
        assert disabled.status_code == 200

        client.cookies.set(COOKIE_NAME, user_token)
        _assert_auth_required(client.get("/api/auth/me"))


def test_role_change_invalidates_existing_session(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        admin_token = _ready_admin(client)
        created = client.post(
            "/api/users",
            json={"username": "role-user", "password": "RoleUser12345", "role": "viewer"},
        )
        assert created.status_code == 200

        user_token, _ = _login(client, "role-user", "RoleUser12345")
        assert client.get("/api/auth/me").status_code == 200

        client.cookies.set(COOKIE_NAME, admin_token)
        changed = client.patch("/api/users/role-user", json={"role": "reviewer"})
        assert changed.status_code == 200
        assert changed.json()["role"] == "reviewer"

        client.cookies.set(COOKIE_NAME, user_token)
        _assert_auth_required(client.get("/api/auth/me"))


def test_password_reset_invalidates_existing_session(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        admin_token = _ready_admin(client)
        created = client.post(
            "/api/users",
            json={"username": "reset-user", "password": "BeforeReset123", "role": "operator"},
        )
        assert created.status_code == 200

        user_token, _ = _login(client, "reset-user", "BeforeReset123")
        assert client.get("/api/auth/me").status_code == 200

        client.cookies.set(COOKIE_NAME, admin_token)
        reset = client.post(
            "/api/users/reset-user/reset-password",
            json={"password": "AfterReset1234", "must_change_password": False},
        )
        assert reset.status_code == 200

        client.cookies.set(COOKIE_NAME, user_token)
        _assert_auth_required(client.get("/api/auth/me"))

        failed_old_password = client.post(
            "/api/auth/login",
            json={"username": "reset-user", "password": "BeforeReset123"},
        )
        assert failed_old_password.status_code == 401
        assert failed_old_password.json()["error"]["code"] == "AUTH_FAILED"

        new_token, _ = _login(client, "reset-user", "AfterReset1234")
        assert new_token != user_token
        assert client.get("/api/auth/me").status_code == 200
