from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import Workbook

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


def workbook_bytes(headers: list[str], rows: list[list[object]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "数据"
    ws.append(headers)
    for row in rows:
        ws.append(row)
    stream = BytesIO()
    wb.save(stream)
    return stream.getvalue()


def auth_headers(client: TestClient) -> dict[str, str]:
    login = client.post("/api/auth/login", json={"username": "admin", "password": "Ab3dEf7Gh9"})
    return {"Authorization": f"Bearer {login.json()['token']}"}


def test_product_flow(tmp_path: Path) -> None:
    client = TestClient(create_app(make_settings(tmp_path)))
    headers = auth_headers(client)
    source_bytes = workbook_bytes(["物料号", "名称", "型号"], [["0001", "环氧玻璃布板", "3240"]])
    target_bytes = workbook_bytes(["集团码", "名称", "牌号"], [["G100", "环氧玻璃布板", "3240"]])

    source = client.post(
        "/api/files/upload?role=source",
        files={"file": ("source.xlsx", source_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=headers,
    )
    target = client.post(
        "/api/files/upload?role=target",
        files={"file": ("target.xlsx", target_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=headers,
    )
    assert source.status_code == 200
    assert target.status_code == 200
    source_id = source.json()["file"]["file_id"]
    target_id = target.json()["file"]["file_id"]

    config = {
        "source_sheet": "数据",
        "source_header_row": 1,
        "target_sheet": "数据",
        "target_header_row": 1,
        "source_id_column": "物料号",
        "group_code_column": "集团码",
        "mappings": [
            {"source_header": "名称", "target_header": "名称", "weight": 0.4, "method": "hybrid", "name": "名称"},
            {"source_header": "型号", "target_header": "牌号", "weight": 0.6, "method": "hybrid", "name": "型号", "critical": True},
        ],
        "threshold": 0.85,
        "review_threshold": 0.75,
        "top_n": 5,
        "candidate_limit": 50,
    }
    dry = client.post(
        "/api/wizard/dry-run",
        json={"source_file_id": source_id, "target_file_id": target_id, "config": config, "sample_rows": 10, "target_sample_rows": 100},
        headers=headers,
    )
    assert dry.status_code == 200
    assert dry.json()["summary"]["matched"] == 1

    published = client.post("/api/profiles/publish", json={"name": "demo", "description": "test", "config": config}, headers=headers)
    assert published.status_code == 200
    assert published.json()["name"] == "demo"

    created = client.post(
        "/api/tasks",
        json={"profile_name": "demo", "source_file_id": source_id, "target_file_id": target_id},
        headers=headers,
    )
    assert created.status_code == 200
    task_id = created.json()["task_id"]
    task = client.get(f"/api/tasks/{task_id}", headers=headers)
    assert task.status_code == 200
    assert task.json()["status"] == "COMPLETED"
    result = client.get(f"/api/tasks/{task_id}/result", headers=headers)
    assert result.status_code == 200
    assert result.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
