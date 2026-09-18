from __future__ import annotations

from io import BytesIO
from pathlib import Path
import time

from fastapi.responses import FileResponse
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook


def _xlsx(headers: list[str], rows: list[list[str]], sheet_name: str) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_name
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def _upload(client: TestClient, role: str, name: str, payload: bytes) -> dict[str, object]:
    response = client.post(
        "/api/files/upload",
        data={"role": role},
        files={"file": (name, payload, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 200, response.text
    return response.json()["file"]


def _prepare_task(
    client: TestClient,
    *,
    source_name: str = "source.xlsx",
    target_name: str = "target.xlsx",
    source_bytes: bytes | None = None,
    target_bytes: bytes | None = None,
) -> dict[str, object]:
    source_payload = source_bytes or _xlsx(
        ["物料号", "物料名称"],
        [["S001", "测试电阻"], ["S002", "测试电容"]],
        "待匹配物料",
    )
    target_payload = target_bytes or _xlsx(
        ["集团码", "物料名称"],
        [["G001", "测试电阻"], ["G002", "测试电容"]],
        "集团码标准",
    )
    source = _upload(client, "source", source_name, source_payload)
    target = _upload(client, "target", target_name, target_payload)
    catalog_response = client.post(
        "/api/catalogs",
        json={
            "name": "任务原始文件测试目录",
            "source_file_id": target["file_id"],
            "group_code_column": "集团码",
        },
    )
    assert catalog_response.status_code == 200, catalog_response.text
    catalog = catalog_response.json()
    draft = client.post("/api/task-drafts", json={}).json()
    data_response = client.put(
        f"/api/task-drafts/{draft['draft_id']}/data",
        json={
            "source_file_id": source["file_id"],
            "catalog_version_id": catalog["version_id"],
        },
    )
    assert data_response.status_code == 200, data_response.text
    rules = {
        "source_id_column": "物料号",
        "scope_mode": "GLOBAL",
        "rules": [
            {
                "id": "name",
                "source": {"fields": ["物料名称"]},
                "target": {"fields": ["物料名称"]},
                "matcher": "exact",
                "weight": 100,
            }
        ],
        "decision": {
            "success_threshold": 80,
            "review_enabled": True,
            "review_threshold": 50,
            "top_n": 2,
        },
        "retrieval": {"mode": "scan", "retrieval_top_k": 10, "oversample": 2},
        "advanced": {},
    }
    rules_response = client.put(f"/api/task-drafts/{draft['draft_id']}/rules", json=rules)
    assert rules_response.status_code == 200, rules_response.text
    return {
        "draft_id": draft["draft_id"],
        "source": source,
        "target": target,
        "catalog": catalog,
        "source_bytes": source_payload,
        "target_bytes": target_payload,
    }


def _start(client: TestClient, prepared: dict[str, object]) -> dict[str, object]:
    response = client.post(f"/api/task-drafts/{prepared['draft_id']}/start")
    assert response.status_code == 202, response.text
    return response.json()


def _wait(client: TestClient, task_id: str) -> dict[str, object]:
    for _ in range(300):
        task = client.get(f"/api/tasks/{task_id}").json()
        if task["status"] in {"COMPLETED", "FAILED"}:
            return task
        time.sleep(0.01)
    raise AssertionError("task timeout")


def test_new_task_freezes_both_original_inputs_and_downloads_exact_bytes(authed: TestClient) -> None:
    source_name = "客户物料清单.xlsx"
    target_name = "集团码标准表_v3.xlsx"
    prepared = _prepare_task(authed, source_name=source_name, target_name=target_name)
    task = _start(authed, prepared)
    task_id = str(task["task_id"])

    snapshot = task["config_snapshot"]["advanced"]["input_assets"]
    assert snapshot["source"]["file_id"] == prepared["source"]["file_id"]
    assert snapshot["source"]["original_name"] == source_name
    assert snapshot["target"]["file_id"] == prepared["target"]["file_id"]
    assert snapshot["target"]["catalog_version_id"] == prepared["catalog"]["version_id"]
    assert snapshot["target"]["original_name"] == target_name

    assets_response = authed.get(f"/api/tasks/{task_id}/input-assets")
    assert assets_response.status_code == 200
    assets = assets_response.json()
    assert assets["source"]["original_name"] == source_name
    assert assets["target"]["original_name"] == target_name
    assert assets["source"]["available"] is True
    assert assets["target"]["available"] is True
    exposed = str(assets).lower()
    assert "file_id" not in exposed
    assert "stored_path" not in exposed
    assert "sha256" not in exposed

    source_download = authed.get(f"/api/tasks/{task_id}/input-files/source")
    target_download = authed.get(f"/api/tasks/{task_id}/input-files/target")
    assert source_download.status_code == 200
    assert target_download.status_code == 200
    assert source_download.content == prepared["source_bytes"]
    assert target_download.content == prepared["target_bytes"]
    assert source_download.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert int(source_download.headers["content-length"]) == len(prepared["source_bytes"])

    # There is deliberately no filesystem-path parameter in the contract. An
    # attacker-supplied query string cannot redirect the download to /etc/passwd.
    ignored_path = authed.get(f"/api/tasks/{task_id}/input-files/source?path=/etc/passwd")
    assert ignored_path.status_code == 200
    assert ignored_path.content == prepared["source_bytes"]

    route = next(
        route
        for route in authed.app.routes
        if getattr(route, "path", "") == "/api/tasks/{task_id}/input-files/{asset_role}"
    )
    assert route.endpoint.__annotations__["return"] is FileResponse


def test_old_task_stays_on_old_target_and_same_name_source_after_new_uploads(authed: TestClient) -> None:
    prepared = _prepare_task(
        authed,
        source_name="同名源数据.xlsx",
        target_name="集团码标准表.xlsx",
    )
    task = _start(authed, prepared)
    task_id = str(task["task_id"])

    new_source_bytes = _xlsx(["物料号", "物料名称"], [["N001", "后来上传的新源数据"]], "新源")
    new_target_bytes = _xlsx(["集团码", "物料名称"], [["NEW001", "后来发布的新标准"]], "新标准")
    new_source = _upload(authed, "source", "同名源数据.xlsx", new_source_bytes)
    new_target = _upload(authed, "target", "集团码标准表.xlsx", new_target_bytes)
    assert new_source["file_id"] != prepared["source"]["file_id"]
    assert new_target["file_id"] != prepared["target"]["file_id"]

    new_version = authed.post(
        f"/api/catalogs/{prepared['catalog']['catalog_id']}/versions",
        json={
            "source_file_id": new_target["file_id"],
            "group_code_column": "集团码",
            "activate": True,
        },
    )
    assert new_version.status_code == 200, new_version.text
    assert new_version.json()["version_id"] != prepared["catalog"]["version_id"]

    assert authed.get(f"/api/tasks/{task_id}/input-files/source").content == prepared["source_bytes"]
    assert authed.get(f"/api/tasks/{task_id}/input-files/target").content == prepared["target_bytes"]

    assets = authed.get(f"/api/tasks/{task_id}/input-assets").json()
    assert assets["source"]["original_name"] == "同名源数据.xlsx"
    assert assets["target"]["original_name"] == "集团码标准表.xlsx"


def test_start_refuses_untraceable_input_and_historical_missing_file_is_friendly(authed: TestClient) -> None:
    prepared = _prepare_task(authed)
    source_id = str(prepared["source"]["file_id"])
    source_record = authed.app.state.files.get(source_id)
    source_path = Path(str(source_record["stored_path"]))
    before = len(authed.get("/api/tasks").json())
    source_path.unlink()

    refused = authed.post(f"/api/task-drafts/{prepared['draft_id']}/start")
    assert refused.status_code == 404
    assert refused.json()["error"]["code"] == "ORIGINAL_FILE_UNAVAILABLE"
    assert len(authed.get("/api/tasks").json()) == before

    # Recreate a valid task, then simulate storage loss after the calculation.
    prepared2 = _prepare_task(authed, source_name="历史源文件.xlsx")
    task = _start(authed, prepared2)
    task_id = str(task["task_id"])
    _wait(authed, task_id)
    record = authed.app.state.files.get(str(prepared2["source"]["file_id"]))
    Path(str(record["stored_path"])).unlink()

    assets = authed.get(f"/api/tasks/{task_id}/input-assets").json()
    assert assets["source"]["available"] is False
    assert assets["source"]["message"] == "该历史任务的原始文件已无法确认"
    missing = authed.get(f"/api/tasks/{task_id}/input-files/source")
    assert missing.status_code == 404
    assert missing.json()["error"]["message"] == "该历史任务的原始文件已无法确认"


def test_legacy_exact_recovery_never_guesses_by_filename_and_blocks_stored_path_escape(authed: TestClient) -> None:
    prepared = _prepare_task(authed, source_name="可重复名称.xlsx", target_name="旧标准.xlsx")
    task = _start(authed, prepared)
    task_id = str(task["task_id"])
    _wait(authed, task_id)

    meta = authed.app.state.meta
    with meta.connect() as connection:
        connection.execute("DELETE FROM task_input_assets WHERE task_id=?", (task_id,))

    # Old tasks created before the new freeze table can still recover from the
    # exact task.source_file_id + task.catalog_version_id relationships.
    assert authed.get(f"/api/tasks/{task_id}/input-files/source").content == prepared["source_bytes"]
    assert authed.get(f"/api/tasks/{task_id}/input-files/target").content == prepared["target_bytes"]

    # A later same-name upload must never be selected as a substitute.
    _upload(
        authed,
        "source",
        "可重复名称.xlsx",
        _xlsx(["物料号", "物料名称"], [["OTHER", "不是原文件"]], "替代文件"),
    )
    with meta.connect() as connection:
        connection.execute("DELETE FROM files WHERE file_id=?", (prepared["source"]["file_id"],))
    source_assets = authed.get(f"/api/tasks/{task_id}/input-assets").json()
    assert source_assets["source"]["available"] is False
    assert source_assets["source"]["message"] == "该历史任务的原始文件已无法确认"

    # Even if metadata is tampered to point outside the managed uploads directory,
    # the task-scoped endpoint refuses to serve arbitrary system files.
    target_id = str(prepared["target"]["file_id"])
    with meta.connect() as connection:
        connection.execute("UPDATE files SET stored_path='/etc/passwd' WHERE file_id=?", (target_id,))
    escaped = authed.get(f"/api/tasks/{task_id}/input-files/target")
    assert escaped.status_code == 404
    assert escaped.json()["error"]["code"] == "ORIGINAL_FILE_UNAVAILABLE"


def test_chinese_and_long_original_filename_is_safe(authed: TestClient) -> None:
    long_name = ("超长中文原始物料清单_" + "甲乙丙丁" * 55 + ".xlsx")
    prepared = _prepare_task(authed, source_name=long_name)
    task = _start(authed, prepared)
    response = authed.get(f"/api/tasks/{task['task_id']}/input-files/source")
    assert response.status_code == 200
    assert response.content == prepared["source_bytes"]
    disposition = response.headers["content-disposition"]
    assert "\r" not in disposition and "\n" not in disposition
    assert "filename*" in disposition.lower()
    assert len(disposition) < 1200


def test_original_input_download_requires_login(client: TestClient) -> None:
    response = client.get("/api/tasks/not-a-real-task/input-files/source")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
