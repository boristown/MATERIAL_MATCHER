from __future__ import annotations

import time

from fastapi.testclient import TestClient


def _upload_csv(client: TestClient, *, role: str, name: str, content: str) -> dict[str, object]:
    response = client.post(
        "/api/files/upload",
        data={"role": role},
        files={"file": (name, content.encode("utf-8"), "text/csv")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_dual_excel_upload_draft_restore_and_start(authed: TestClient) -> None:
    source_upload = _upload_csv(
        authed,
        role="source",
        name="待匹配数据.csv",
        content="物料编码,物料名称,型号,品牌\nM001,测试电机,X1,ACME\n",
    )
    target_upload = _upload_csv(
        authed,
        role="target",
        name="集团码标准数据.csv",
        content="集团码,物料名称,型号,生产厂家\nG001,测试电机,X1,ACME\n",
    )

    source_file = source_upload["file"]
    target_file = target_upload["file"]
    source_inspection = source_upload["inspection"]
    target_inspection = target_upload["inspection"]

    source_sheet = source_inspection["sheets"][0]
    target_sheet = target_inspection["sheets"][0]
    assert source_inspection["recommended_sheet"] == "CSV"
    assert target_inspection["recommended_sheet"] == "CSV"
    assert source_sheet["recommended_header_row"] == 1
    assert target_sheet["recommended_header_row"] == 1
    assert source_sheet["row_count_estimate"] == 1
    assert target_sheet["row_count_estimate"] == 1
    assert {column["header"] for column in source_sheet["columns"]} >= {"物料编码", "物料名称", "型号"}
    assert {column["header"] for column in target_sheet["columns"]} >= {"集团码", "物料名称", "型号"}
    assert source_sheet["columns"][0]["samples"]
    assert target_sheet["columns"][0]["samples"]

    created_draft = authed.post("/api/task-drafts", json={"name": "双 Excel 流程测试"})
    assert created_draft.status_code == 200, created_draft.text
    draft_id = created_draft.json()["draft_id"]

    catalog = authed.post(
        "/api/catalogs",
        json={
            "name": "双 Excel 流程测试-自动标准数据",
            "source_file_id": target_file["file_id"],
            "group_code_column": "集团码",
        },
    )
    assert catalog.status_code == 200, catalog.text
    catalog_version_id = catalog.json()["version_id"]

    config = {
        "source_id_column": "物料编码",
        "scope_mode": "GLOBAL",
        "rules": [
            {
                "id": "name-model",
                "source": {"fields": ["物料名称", "型号"], "combine": "concat", "separator": " ", "pipeline": []},
                "target": {"fields": ["物料名称", "型号"], "combine": "concat", "separator": " ", "pipeline": []},
                "matcher": "fuzzy",
                "weight": 70,
                "critical": False,
                "matcher_options": {},
            },
            {
                "id": "brand",
                "source": {"fields": ["品牌"], "combine": "concat", "separator": " ", "pipeline": []},
                "target": {"fields": ["生产厂家"], "combine": "concat", "separator": " ", "pipeline": []},
                "matcher": "fuzzy",
                "weight": 30,
                "critical": False,
                "matcher_options": {},
            },
        ],
        "decision": {"success_threshold": 88, "review_enabled": True, "review_threshold": 75, "top_n": 5},
        "retrieval": {"mode": "scan", "retrieval_top_k": 20, "oversample": 2},
        "advanced": {
            "workspace_target": {
                "file_id": target_file["file_id"],
                "group_code_column": "集团码",
            }
        },
    }

    patched = authed.patch(
        f"/api/task-drafts/{draft_id}",
        json={
            "name": "双 Excel 流程测试",
            "source_file_id": source_file["file_id"],
            "catalog_version_id": catalog_version_id,
            "config_document": config,
        },
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["source_file_id"] == source_file["file_id"]
    assert patched.json()["catalog_version_id"] == catalog_version_id

    saved_data = authed.put(
        f"/api/task-drafts/{draft_id}/data",
        json={"source_file_id": source_file["file_id"], "catalog_version_id": catalog_version_id},
    )
    assert saved_data.status_code == 200, saved_data.text
    saved_rules = authed.put(f"/api/task-drafts/{draft_id}/rules", json=config)
    assert saved_rules.status_code == 200, saved_rules.text

    # 模拟浏览器刷新 / 关闭后重新进入原 URL：所有 STEP1 状态都来自后端草稿。
    restored = authed.get(f"/api/task-drafts/{draft_id}")
    assert restored.status_code == 200, restored.text
    restored_document = restored.json()["config_document"]
    assert restored.json()["source_file_id"] == source_file["file_id"]
    assert restored.json()["catalog_version_id"] == catalog_version_id
    assert restored_document["advanced"]["workspace_target"] == {
        "file_id": target_file["file_id"],
        "group_code_column": "集团码",
    }
    assert restored_document["decision"]["success_threshold"] == 88
    assert "review_threshold" not in restored_document["decision"]
    assert restored_document["rules"][0]["source"]["fields"] == ["物料名称", "型号"]
    assert restored_document["rules"][0]["weight"] == 70
    assert restored_document["rules"][0]["matcher"] == "fuzzy"

    target_reload = authed.get(f"/api/files/{target_file['file_id']}/inspection")
    assert target_reload.status_code == 200, target_reload.text
    assert target_reload.json()["file"]["original_name"] == "集团码标准数据.csv"

    # 相同标准数据再次上传会得到相同 SHA；STEP1 可据此自动复用既有 catalog/version 与向量索引。
    duplicate_target = _upload_csv(
        authed,
        role="target",
        name="集团码标准数据-再次上传.csv",
        content="集团码,物料名称,型号,生产厂家\nG001,测试电机,X1,ACME\n",
    )["file"]
    assert duplicate_target["file_id"] != target_file["file_id"]
    assert duplicate_target["sha256"] == target_file["sha256"]

    started = authed.post(f"/api/task-drafts/{draft_id}/start")
    assert started.status_code == 202, started.text
    task_id = started.json()["task_id"]
    deadline = time.time() + 5
    task = started.json()
    while task["status"] not in {"COMPLETED", "FAILED"} and time.time() < deadline:
        time.sleep(0.05)
        task_response = authed.get(f"/api/tasks/{task_id}")
        assert task_response.status_code == 200, task_response.text
        task = task_response.json()
    assert task["status"] == "COMPLETED", task
