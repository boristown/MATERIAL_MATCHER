from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from material_matcher.api.app import create_app
from material_matcher.settings import Settings


@pytest.fixture()
def client(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "etc",
        log_dir=tmp_path / "log",
        admin_password="Ab3dEf7Gh9",
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture()
def authed(client: TestClient) -> TestClient:
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "Ab3dEf7Gh9"},
    )
    assert response.status_code == 200
    return client
