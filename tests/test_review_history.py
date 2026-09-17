from __future__ import annotations

import contextlib
import sqlite3
import time
from typing import Any

from fastapi.testclient import TestClient

SCHEME = "电子元器件集团码匹配方案"


def _workbook(rows: list[list[Any]], header: list[str], title: str) -> bytes:
    from openpyxl import Workbook
    from io import BytesIO

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = title
    sheet.append(["说明"])
    sheet.append(header)
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _wait(authed: TestClient, task_id: str) -> dict[str, Any]:
    for _ in range(2000):
        task = authed.get(f"/api/tasks/{task_id}").json()
        if task["status"] in {"COMPLETED", "FAILED"}:
            return task
        time.sleep(0.01)
    raise AssertionError("task timeout")


def _complete(authed: TestClient, *, draft_name: str, scheme: str | None, source_rows: list[list[Any]]) -> str:
    source = authed.post("/api/files/upload", data={"role": "source"}, files={"file": ("source.xlsx", _workbook(source_rows, ["物料号", "物料名称", "型号"], "物料"), "application/octet-stream")}).json()
    target = authed.post("/api/files/upload", data={"role": "target"}, files={"file": ("target.xlsx", _workbook([["G1", "电阻", "R10"], ["G2", "电容", "C10"]], ["集团码", "物料名称", "型号"], "集团"), "application/octet-stream")}).json()
    catalog = authed.post("/api/catalogs", json={"name": f"目录-{draft_name}", "source_file_id": target["file"]["file_id"], "group_code_column": "集团码"}).json()
    draft = authed.post("/api/task-drafts", json={"name": draft_name}).json()
    authed.put(f"/api/task-drafts/{draft['draft_id']}/data", json={"source_file_id": source["file"]["file_id"], "catalog_version_id": catalog["version_id"]})
    advanced: dict[str, Any] = {"scheme_display_name": scheme} if scheme else {}
    rules = {
        "source_id_column": "物料号",
        "scope_mode": "GLOBAL",
        "rules": [{"id": "name", "source": {"fields": ["物料名称"]}, "target": {"fields": ["物料名称"]}, "matcher": "fuzzy", "weight": 80}, {"id": "model", "source": {"fields": ["型号"]}, "target": {"fields": ["型号"]}, "matcher": "exact", "weight": 100}],
        "decision": {"success_threshold": 60, "review_enabled": True, "review_threshold": 20, "top_n": 3},
        "advanced": advanced,
    }
    assert authed.put(f"/api/task-drafts/{draft['draft_id']}/rules", json=rules).status_code == 200
    task_id = authed.post(f"/api/task-drafts/{draft['draft_id']}/start").json()["task_id"]
    assert _wait(authed, task_id)["status"] == "COMPLETED"
    return task_id


def _set_times(authed: TestClient, task_id: str, started_at: str, finished_at: str) -> None:
    repo = authed.app.state.tasks.repo
    with sqlite3.connect(repo.db_path) as connection:
        connection.execute("UPDATE tasks SET started_at=?, finished_at=? WHERE task_id=?", (started_at, finished_at, task_id))
        connection.commit()


def test_review_history_orders_and_numbers_each_scheme_computation(authed: TestClient) -> None:
    first = _complete(authed, draft_name="SMOKE-1.1.9-run-a", scheme=SCHEME, source_rows=[["0001", "电阻", "R10"], ["0002", "未知物", "Z9"]])
    second = _complete(authed, draft_name="SMOKE-1.1.9-run-b", scheme=SCHEME, source_rows=[["0001", "电阻", "R10"], ["0003", "电容器", "C10"]])
    _set_times(authed, first, "2026-09-17T10:00:00+08:00", "2026-09-17T10:00:05+08:00")
    _set_times(authed, second, "2026-09-17T18:55:07+08:00", "2026-09-17T18:55:08+08:00")

    history = authed.get("/api/tasks/review-history").json()
    assert [row["task_id"] for row in history if row["task_id"] in {first, second}] == [second, first]

    by_id = {row["task_id"]: row for row in history}
    assert by_id[first]["sequence"] == 1 and by_id[second]["sequence"] == 2
    assert by_id[first]["sequence_total"] == 2
    assert by_id[second]["scheme_name"] == SCHEME
    assert by_id[second]["started_at"] == "2026-09-17T18:55:07+08:00"
    assert by_id[second]["finished_at"] == "2026-09-17T18:55:08+08:00"
    payload = authed.get("/api/tasks/review-history").text
    assert "SMOKE-1.1.9" not in payload and "run-a" not in payload

    for row_id in (first, second):
        summary = authed.get(f"/api/tasks/{row_id}/workbench/summary").json()
        row = by_id[row_id]
        assert row["matched"] == summary["automatic_matched"]
        assert row["review"] == summary["pending_review"]
        assert row["confirmed"] == summary["confirmed"]
        assert row["unmatched"] == summary["unmatched"]
        assert row["total"] == row["matched"] + row["review"] + row["confirmed"] + row["unmatched"] > 0

    # Ordinals must be stable across refreshes.
    again = {row["task_id"]: row for row in authed.get("/api/tasks/review-history").json()}
    assert (again[first]["sequence"], again[second]["sequence"]) == (1, 2)


def test_review_history_keeps_unattributed_tasks_without_fake_sequence(authed: TestClient) -> None:
    named = _complete(authed, draft_name="SMOKE-named", scheme=SCHEME, source_rows=[["0001", "电阻", "R10"]])
    anonymous = _complete(authed, draft_name="TASK-legacy-no-scheme", scheme=None, source_rows=[["0002", "电容", "C10"]])
    by_id = {row["task_id"]: row for row in authed.get("/api/tasks/review-history").json()}
    assert by_id[anonymous]["scheme_name"] == "未命名方案"
    assert by_id[anonymous]["sequence"] is None
    assert by_id[anonymous]["sequence_total"] is None
    assert by_id[named]["sequence"] == 1
    assert "TASK-legacy" not in authed.get("/api/tasks/review-history").text


def test_review_history_uses_a_single_aggregate_query(authed: TestClient) -> None:
    for index in range(3):
        task_id = _complete(authed, draft_name=f"SMOKE-perf-{index}", scheme=SCHEME, source_rows=[[f"000{index}", "电阻", "R10"]])
        _set_times(authed, task_id, f"2026-09-1{index+1}T09:00:00+08:00", f"2026-09-1{index+1}T09:00:01+08:00")

    service = authed.app.state.tasks
    repository = service.repo
    original = repository.connect
    seen: list[str] = []

    class CountingConnection:
        def __init__(self, connection: sqlite3.Connection) -> None:
            self._connection = connection

        def execute(self, sql: str, parameters: Any = ...) -> Any:
            seen.append(str(sql))
            if parameters is ...:
                return self._connection.execute(sql)
            return self._connection.execute(sql, parameters)

        def __getattr__(self, name: str) -> Any:
            return getattr(self._connection, name)

    @contextlib.contextmanager
    def connect() -> Any:
        with original() as connection:
            yield CountingConnection(connection)

    repository.connect = connect  # type: ignore[method-assign]
    try:
        items = service.review_history()
    finally:
        repository.connect = original  # type: ignore[method-assign]
    aggregates = [sql for sql in seen if "match_items" in sql]
    assert len(aggregates) == 1
    assert "GROUP BY" in aggregates[0]
    assert len(items) >= 3
