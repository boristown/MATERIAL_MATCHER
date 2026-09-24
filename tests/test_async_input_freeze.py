from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from material_matcher.api.app import create_app
from material_matcher.domain.errors import DomainError
from material_matcher.services.task_input_asset_service import TaskInputAssetService
from material_matcher.settings import Settings

from conftest import BOOTSTRAP_ADMIN_PASSWORD, TEST_ADMIN_PASSWORD
from test_task_input_assets import _prepare_task, _wait


def _async_settings(tmp_path):
    return Settings(
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "etc",
        log_dir=tmp_path / "log",
        admin_password=BOOTSTRAP_ADMIN_PASSWORD,
        worker_poll_seconds=0.01,
        embedding_model_root=tmp_path / "models",
        web_dist_dir=tmp_path / "web-dist",
    )


@pytest.fixture()
def async_client(tmp_path, monkeypatch):
    monkeypatch.delenv("MATERIAL_MATCHER_SYNC_FREEZE", raising=False)
    settings = _async_settings(tmp_path)
    client = TestClient(create_app(settings))
    response = client.post("/api/auth/login", json={"username": "admin", "password": BOOTSTRAP_ADMIN_PASSWORD})
    if response.json().get("user", {}).get("must_change_password"):
        client.post("/api/auth/change-password", json={"current_password": BOOTSTRAP_ADMIN_PASSWORD, "new_password": TEST_ADMIN_PASSWORD})
        client.post("/api/auth/login", json={"username": "admin", "password": TEST_ADMIN_PASSWORD})
    return client


def _wait_until_freeze_done(client: TestClient, task_id: str, timeout: float = 40.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = client.get(f"/api/tasks/{task_id}").json()
        if task["status"] != "FREEZING":
            return task
        time.sleep(0.02)
    raise AssertionError("task stuck in FREEZING")


def test_start_returns_freezing_immediately_and_freeze_runs_in_background(async_client, monkeypatch):
    original = TaskInputAssetService.freeze_draft

    def slow(self, draft_id):
        time.sleep(1.2)
        return original(self, draft_id)

    monkeypatch.setattr(TaskInputAssetService, "freeze_draft", slow)
    prepared = _prepare_task(async_client)
    started_at = time.monotonic()
    response = async_client.post(f"/api/task-drafts/{prepared['draft_id']}/start")
    elapsed = time.monotonic() - started_at
    assert response.status_code == 202, response.text
    assert elapsed < 1.0, "POST must not wait for the heavy freeze"
    task = response.json()
    assert task["status"] == "FREEZING"
    settled = _wait_until_freeze_done(async_client, str(task["task_id"]))
    assert settled["status"] in {"PENDING", "PREPARING", "RUNNING", "COMPLETED"}
    assets = async_client.get(f"/api/tasks/{task['task_id']}/input-assets")
    assert assets.status_code == 200
    summary = assets.json()
    assert summary["composite"] is False
    assert summary["source"] and summary["target"]


def test_freeze_failure_surfaces_on_task_not_http(async_client, monkeypatch):
    def boom(self, draft_id):
        raise DomainError("ORIGINAL_FILE_UNAVAILABLE", "原始文件已丢失，无法冻结", status_code=404)

    monkeypatch.setattr(TaskInputAssetService, "freeze_draft", boom)
    prepared = _prepare_task(async_client)
    response = async_client.post(f"/api/task-drafts/{prepared['draft_id']}/start")
    assert response.status_code == 202, response.text
    task = response.json()
    settled = _wait_until_freeze_done(async_client, str(task["task_id"]))
    assert settled["status"] == "FAILED"
    assert settled["error_code"] == "INPUT_FREEZE_FAILED"
    assert "原始文件已丢失" in str(settled["error_message"])


def test_restart_abandons_stale_freezing_tasks(tmp_path, monkeypatch):
    monkeypatch.delenv("MATERIAL_MATCHER_SYNC_FREEZE", raising=False)
    settings = _async_settings(tmp_path)
    client = TestClient(create_app(settings))
    login = client.post("/api/auth/login", json={"username": "admin", "password": BOOTSTRAP_ADMIN_PASSWORD})
    if login.json().get("user", {}).get("must_change_password"):
        client.post("/api/auth/change-password", json={"current_password": BOOTSTRAP_ADMIN_PASSWORD, "new_password": TEST_ADMIN_PASSWORD})
        client.post("/api/auth/login", json={"username": "admin", "password": TEST_ADMIN_PASSWORD})
    prepared = _prepare_task(client)
    service = client.app.state.tasks
    task = service.start(str(prepared["draft_id"]), actor="admin", initial_status="FREEZING")
    assert task["status"] == "FREEZING"
    assert service.pending_freezes()
    del client
    rebound = TestClient(create_app(settings))
    rebound.post("/api/auth/login", json={"username": "admin", "password": TEST_ADMIN_PASSWORD})
    data = rebound.get(f"/api/tasks/{task['task_id']}").json()
    assert data["status"] == "FAILED"
    assert data["error_code"] == "INPUT_FREEZE_INTERRUPTED"
    assert rebound.get(f"/api/tasks/{task['task_id']}").json()["error_message"]


def test_sync_mode_keeps_legacy_pending_semantics(authed):
    prepared = _prepare_task(authed)
    response = authed.post(f"/api/task-drafts/{prepared['draft_id']}/start")
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "PENDING"
    task = _wait(authed, str(response.json()["task_id"]))
    assert task["status"] == "COMPLETED"
