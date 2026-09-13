from __future__ import annotations

from hashlib import sha256
from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import Workbook


def workbook_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "物料"
    sheet.append(["说明"])
    sheet.append(["物料号", "物料名称", "型号"])
    sheet.append(["000123", "电阻", "R10"])
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_auth_and_health(client: TestClient) -> None:
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/tasks").status_code == 401
    bad = client.post("/api/auth/login", json={"username": "admin", "password": "bad"})
    assert bad.status_code == 401
    assert bad.json()["error"]["code"] == "AUTH_FAILED"


def test_draft_to_immutable_task_snapshot(authed: TestClient) -> None:
    source = authed.post("/api/files/upload", data={"role": "source"}, files={"file": ("source.xlsx", workbook_bytes(), "application/octet-stream")})
    target = authed.post("/api/files/upload", data={"role": "target"}, files={"file": ("target.xlsx", workbook_bytes(), "application/octet-stream")})
    assert source.status_code == 200 and target.status_code == 200
    source_body = source.json(); target_body = target.json()
    assert source_body["inspection"]["recommended_sheet"] == "物料"
    catalog = authed.post("/api/catalogs", json={"name": "集团目录", "source_file_id": target_body["file"]["file_id"], "group_code_column": "物料号"}).json()
    draft = authed.post("/api/task-drafts", json={"name": "测试任务"}).json()
    assert authed.put(f'/api/task-drafts/{draft["draft_id"]}/data', json={"source_file_id": source_body["file"]["file_id"], "catalog_version_id": catalog["version_id"]}).status_code == 200
    rules = {"scope_mode": "GLOBAL", "rules": [{"id": "name", "source": {"fields": ["物料名称"]}, "target": {"fields": ["物料名称"]}, "matcher": "fuzzy", "weight": 80}], "decision": {"success_threshold": 90, "review_enabled": True, "review_threshold": 80, "top_n": 5}, "advanced": {}}
    assert authed.put(f'/api/task-drafts/{draft["draft_id"]}/rules', json=rules).status_code == 200
    started = authed.post(f'/api/task-drafts/{draft["draft_id"]}/start')
    assert started.status_code == 202
    task = started.json()
    assert task["profile_id"] is None
    assert task["config_snapshot"]["rules"][0]["weight"] == 80
    assert len(task["config_sha256"]) == 64
    rules["rules"][0]["weight"] = 20
    authed.put(f'/api/task-drafts/{draft["draft_id"]}/rules', json=rules)
    reloaded = authed.get(f'/api/tasks/{task["task_id"]}').json()
    assert reloaded["config_snapshot"]["rules"][0]["weight"] == 80


def test_chunk_upload_validates_hash_and_order(authed: TestClient) -> None:
    payload = workbook_bytes(); digest = sha256(payload).hexdigest()
    initialized = authed.post("/api/uploads/init", json={"role": "source", "original_name": "chunked.xlsx", "total_size": len(payload), "sha256": digest}).json()
    upload_id = initialized["upload_id"]
    wrong_order = authed.put(f"/api/uploads/{upload_id}/chunks/1", content=payload)
    assert wrong_order.status_code == 409
    assert wrong_order.json()["error"]["code"] == "UPLOAD_CHUNK_ORDER"
    assert authed.put(f"/api/uploads/{upload_id}/chunks/0", content=payload).status_code == 200
    completed = authed.post(f"/api/uploads/{upload_id}/complete")
    assert completed.status_code == 200
    assert completed.json()["file"]["sha256"] == digest


def test_old_xls_is_explicitly_rejected(authed: TestClient) -> None:
    response = authed.post("/api/files/upload", data={"role": "source"}, files={"file": ("old.xls", b"fake", "application/octet-stream")})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE"
