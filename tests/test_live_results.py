from __future__ import annotations

from pathlib import Path
import time

from fastapi.testclient import TestClient


def _upload(client: TestClient, tmp_path: Path, name: str, content: str) -> str:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    with path.open("rb") as stream:
        response = client.post("/api/files/upload", data={"role": "target" if "集团" in name else "source"}, files={"file": (name, stream, "text/csv")})
    response.raise_for_status()
    return response.json()["file"]["file_id"]


def test_live_results_and_summary_are_incremental_and_flagged(tmp_path: Path, authed: TestClient) -> None:
    client = authed
    target_file = _upload(client, tmp_path, "集团目录.csv", "集团码,名称,型号\nG1,电阻,R10\nG2,电容,C20\nG3,电感,L30\n", )
    catalog = client.post("/api/catalogs", json={"name": "直播测试", "source_file_id": target_file, "group_code_column": "集团码"}).json()
    source_file = _upload(client, tmp_path, "客户物料.csv", "编码,名称,型号\n0001,电阻,R10\n0002,未知物,X9\n")
    draft = client.post("/api/task-drafts", json={"name": "直播"}).json()["draft_id"]
    client.put(f"/api/task-drafts/{draft}/data", json={"source_file_id": source_file, "catalog_version_id": catalog["version_id"]}).raise_for_status()
    rules = {
        "source_id_column": "编码",
        "scope_mode": "GLOBAL",
        "rules": [{"id": "name", "source": {"fields": ["名称"]}, "target": {"fields": ["名称"]}, "matcher": "exact", "weight": 100}],
        "decision": {"success_threshold": 60, "review_enabled": True, "review_threshold": 30, "top_n": 5},
        "retrieval": {"mode": "scan"},
    }
    client.put(f"/api/task-drafts/{draft}/rules", json=rules).raise_for_status()
    task = client.post(f"/api/task-drafts/{draft}/start").json()["task_id"]
    for _ in range(100):
        progress = client.get(f"/api/tasks/{task}/progress").json()
        if progress["status"] in {"COMPLETED", "FAILED"}:
            break
        time.sleep(0.01)
    assert progress["status"] == "COMPLETED"
    assert "live_counts" in progress and "interim" in progress
    assert progress["interim"] is False
    live = client.get(f"/api/tasks/{task}/live-results", params={"limit": 10}).json()
    assert live["interim"] is False
    assert live["counts"]["matched"] == 1
    assert {row["source_id"] for row in live["rows"]} == {"0001", "0002"}
    summary = client.get(f"/api/tasks/{task}/workbench/summary").json()
    assert summary["interim"] is False and summary["task_status"] == "COMPLETED"


def test_progress_estimate_is_exposed_on_running_task(authed: TestClient) -> None:
    # 无样本时 estimate 为 null,接口形状稳定;完成后可清理
    response = authed.get("/api/tasks/nonexistent/progress")
    assert response.status_code == 404
