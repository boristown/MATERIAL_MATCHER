from __future__ import annotations

from fastapi.testclient import TestClient


def _seed_completed_task(authed: TestClient) -> None:
    meta = authed.app.state.meta
    now = "2026-09-15T19:00:00+08:00"
    config = '{"decision":{"top_n":3}}'
    with meta.connect() as connection:
        connection.execute(
            "INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("eval-task", "准确率验收任务", "source-file", "catalog-v1", None, None, config, "sha", "RESULT", "COMPLETED", 100.0, 2, 2, now, now, now, None, None, None),
        )
        connection.executemany(
            "INSERT INTO match_items VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                ("eval-task", "row-1", "M001", "{}", "MATCHED", "MATCHED", "G001", 99.0, 60.0, 39.0, 0, "G001", now, now),
                ("eval-task", "row-2", "M002", "{}", "REVIEW", "CONFIRMED", "G999", 83.0, 81.0, 2.0, 0, "G002", now, now),
            ],
        )
        connection.executemany(
            "INSERT INTO match_candidates VALUES(?,?,?,?,?,?,?,?)",
            [
                ("eval-task", "row-1", 1, "G001", "{}", 99.0, "{}", 0),
                ("eval-task", "row-2", 1, "G999", "{}", 83.0, "{}", 0),
                ("eval-task", "row-2", 2, "G002", "{}", 81.0, "{}", 0),
            ],
        )


def test_business_evaluation_api_accepts_uploaded_truth_and_returns_errors(authed: TestClient) -> None:
    _seed_completed_task(authed)
    uploaded = authed.post(
        "/api/files/upload",
        data={"role": "supplement"},
        files={"file": ("truth.csv", "物料号,正确集团码\nM001,G001\nM002,G002\nM003,G003\n".encode("utf-8"), "text/csv")},
    )
    assert uploaded.status_code == 200
    truth_file_id = uploaded.json()["file"]["file_id"]

    created = authed.post(
        "/api/tasks/eval-task/evaluations",
        json={
            "truth_file_id": truth_file_id,
            "key_column": "物料号",
            "expected_group_code_column": "正确集团码",
            "key_mode": "source_id",
        },
    )
    assert created.status_code == 200
    result = created.json()
    assert result["task_id"] == "eval-task"
    assert result["metrics"]["truth_rows"] == 3
    assert result["metrics"]["truth_coverage"] == 0.666667
    assert result["metrics"]["top1_accuracy"] == 0.5
    assert result["metrics"]["final_accuracy"] == 1.0
    assert result["metrics"]["candidate_top_n"] == 3
    assert result["metrics"]["candidate_recall_at"]["3"] == 1.0

    history = authed.get("/api/tasks/eval-task/evaluations")
    assert history.status_code == 200
    assert history.json()[0]["run_id"] == result["run_id"]

    detail = authed.get(f"/api/evaluations/{result['run_id']}?include_items=true&only_errors=true")
    assert detail.status_code == 200
    error_keys = {item["truth_key"] for item in detail.json()["items"]}
    assert error_keys == {"M002", "M003"}


def test_business_evaluation_api_requires_supplement_file(authed: TestClient) -> None:
    _seed_completed_task(authed)
    uploaded = authed.post(
        "/api/files/upload",
        data={"role": "source"},
        files={"file": ("truth.csv", "物料号,正确集团码\nM001,G001\n".encode("utf-8"), "text/csv")},
    )
    assert uploaded.status_code == 200
    response = authed.post(
        "/api/tasks/eval-task/evaluations",
        json={
            "truth_file_id": uploaded.json()["file"]["file_id"],
            "key_column": "物料号",
            "expected_group_code_column": "正确集团码",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_FILE_ROLE"
