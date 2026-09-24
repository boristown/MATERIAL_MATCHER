from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from material_matcher.services import versioned_result_service
from material_matcher.services.result_export_service import ResultExportService

from test_task_input_assets import _prepare_task, _wait


@pytest.fixture(autouse=True)
def _clean_registry():
    versioned_result_service._EXPORTING.clear()
    versioned_result_service._EXPORT_ERRORS.clear()
    yield
    versioned_result_service._EXPORTING.clear()
    versioned_result_service._EXPORT_ERRORS.clear()


def _completed_task(authed: TestClient) -> dict:
    prepared = _prepare_task(authed)
    started = authed.post(f"/api/task-drafts/{prepared['draft_id']}/start").json()
    task = _wait(authed, str(started["task_id"]))
    assert task["status"] == "COMPLETED"
    return {**prepared, "task": task}


def _slow_export(monkeypatch, seconds: float = 1.5):
    original = ResultExportService.export_task

    def slow(self, *args, **kwargs):
        time.sleep(seconds)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ResultExportService, "export_task", slow)


def _wait_export_settled(client: TestClient, task_id: str, timeout: float = 40.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = client.get(f"/api/tasks/{task_id}").json()
        if not task.get("exporting"):
            return task
        time.sleep(0.05)
    raise AssertionError("export never settled")


def test_finalize_returns_exporting_immediately_and_file_lands_later(authed, monkeypatch):
    prepared = _completed_task(authed)
    task_id = str(prepared["task"]["task_id"])
    _slow_export(monkeypatch)
    started_at = time.monotonic()
    response = authed.post(f"/api/tasks/{task_id}/finalize", json={"allow_unresolved_review": True})
    assert time.monotonic() - started_at < 1.0
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "EXPORTING"
    busy = authed.get(f"/api/tasks/{task_id}").json()
    assert busy["exporting"] is True
    assert not busy["result_file_id"]
    settled = _wait_export_settled(authed, task_id)
    assert settled["exporting"] is False
    assert settled["result_file_id"]
    download = authed.get(f"/api/tasks/{task_id}/result")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/vnd.openxmlformats")


def test_result_download_during_export_says_wait(authed, monkeypatch):
    prepared = _completed_task(authed)
    task_id = str(prepared["task"]["task_id"])
    _slow_export(monkeypatch, seconds=3.0)
    authed.post(f"/api/tasks/{task_id}/finalize", json={"allow_unresolved_review": True})
    refused = authed.get(f"/api/tasks/{task_id}/result")
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "RESULT_EXPORT_IN_PROGRESS"


def test_duplicate_finalize_while_exporting_reuses_job(authed, monkeypatch):
    prepared = _completed_task(authed)
    task_id = str(prepared["task"]["task_id"])
    _slow_export(monkeypatch, seconds=3.0)
    first = authed.post(f"/api/tasks/{task_id}/finalize", json={"allow_unresolved_review": True})
    second = authed.post(f"/api/tasks/{task_id}/finalize", json={"allow_unresolved_review": True})
    assert first.json()["status"] == second.json()["status"] == "EXPORTING"


def test_export_failure_visible_and_retry_succeeds(authed, monkeypatch):
    prepared = _completed_task(authed)
    task_id = str(prepared["task"]["task_id"])

    def boom(self, *args, **kwargs):
        raise RuntimeError("导出器故障演练")

    monkeypatch.setattr(ResultExportService, "export_task", boom)
    authed.post(f"/api/tasks/{task_id}/finalize", json={"allow_unresolved_review": True})
    settled = _wait_export_settled(authed, task_id)
    assert settled["exporting"] is False
    assert not settled.get("result_file_id")
    assert "导出器故障演练" in str(settled.get("export_error"))
    monkeypatch.undo()
    retry = authed.post(f"/api/tasks/{task_id}/finalize", json={"allow_unresolved_review": True})
    assert retry.json().get("result_file_id") or retry.json()["status"] == "EXPORTING"
    done = _wait_export_settled(authed, task_id)
    assert done["result_file_id"]
    assert not done.get("export_error")


def test_reused_result_returns_synchronously(authed):
    prepared = _completed_task(authed)
    task_id = str(prepared["task"]["task_id"])
    authed.post(f"/api/tasks/{task_id}/finalize", json={"allow_unresolved_review": True})
    settled = _wait_export_settled(authed, task_id)
    assert settled["result_file_id"]
    second = authed.post(f"/api/tasks/{task_id}/finalize", json={"allow_unresolved_review": True})
    assert second.json().get("reused") is True
    assert second.json().get("status") != "EXPORTING"
