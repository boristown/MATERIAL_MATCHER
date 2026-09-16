from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from material_matcher.domain.errors import DomainError
from material_matcher.services.business_evaluation_service import BusinessEvaluationService
from material_matcher.storage.files import FileRepository
from material_matcher.storage.metadata import MetadataRepository


_MATCH_ITEM_COLUMNS = "task_id,source_row_id,source_id,source_payload,original_status,current_status,top1_group_code,top1_score,second_score,score_gap,critical_conflict,final_group_code,created_at,updated_at"
_CANDIDATE_COLUMNS = "task_id,source_row_id,rank,target_group_code,target_payload,score,field_scores,critical_conflict"


def _seed_task(meta: MetadataRepository) -> None:
    now = "2026-09-15T19:00:00+08:00"
    config = '{"decision":{"top_n":10}}'
    with meta.connect() as connection:
        connection.execute(
            "INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("task-1", "验收任务", "source-file", "catalog-v1", None, None, config, "sha", "RESULT", "COMPLETED", 100.0, 3, 3, now, now, now, None, None, None),
        )
        rows = [
            ("task-1", "row-1", "A", "{}", "MATCHED", "MATCHED", "G1", 98.0, 70.0, 28.0, 0, "G1", now, now),
            ("task-1", "row-2", "B", "{}", "REVIEW", "CONFIRMED", "G9", 82.0, 80.0, 2.0, 0, "G2", now, now),
            ("task-1", "row-3", "C", "{}", "UNMATCHED", "UNMATCHED", "G8", 40.0, 39.0, 1.0, 0, None, now, now),
        ]
        connection.executemany(f"INSERT INTO match_items({_MATCH_ITEM_COLUMNS}) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        candidates = [
            ("task-1", "row-1", 1, "G1", "{}", 98.0, "{}", 0),
            ("task-1", "row-2", 1, "G9", "{}", 82.0, "{}", 0),
            ("task-1", "row-2", 2, "G2", "{}", 80.0, "{}", 0),
            ("task-1", "row-3", 1, "G8", "{}", 40.0, "{}", 0),
            ("task-1", "row-3", 4, "G3", "{}", 37.0, "{}", 0),
        ]
        connection.executemany(f"INSERT INTO match_candidates({_CANDIDATE_COLUMNS}) VALUES(?,?,?,?,?,?,?,?)", candidates)


def _truth_file(files: FileRepository) -> str:
    content = "物料号,正确集团码\nA,G1\nB,G2\nC,G3\nX,G9\n".encode("utf-8")
    record = files.save_stream("truth.csv", "supplement", BytesIO(content), 1024 * 1024)
    return str(record["file_id"])


def test_business_evaluation_separates_model_and_human_quality(tmp_path: Path) -> None:
    meta = MetadataRepository(tmp_path / "data/meta/material_matcher.db")
    files = FileRepository(tmp_path / "data", meta)
    _seed_task(meta)
    service = BusinessEvaluationService(meta, files)

    result = service.evaluate(
        "task-1",
        truth_file_id=_truth_file(files),
        key_column="物料号",
        expected_group_code_column="正确集团码",
    )
    metrics = result["metrics"]
    assert metrics["truth_rows"] == 4
    assert metrics["evaluated_rows"] == 3
    assert metrics["truth_coverage"] == 0.75
    assert metrics["top1_accuracy"] == pytest.approx(1 / 3, abs=1e-6)
    assert metrics["final_accuracy"] == pytest.approx(2 / 3, abs=1e-6)
    assert metrics["automatic_rows"] == 1
    assert metrics["automatic_accuracy"] == 1.0
    assert metrics["review_rows"] == 1
    assert metrics["unmatched_rows"] == 1
    assert metrics["resolved_rate"] == pytest.approx(2 / 3, abs=1e-6)
    assert metrics["candidate_top_n"] == 10
    assert metrics["candidate_recall_at"]["1"] == pytest.approx(1 / 3, abs=1e-6)
    assert metrics["candidate_recall_at"]["3"] == pytest.approx(2 / 3, abs=1e-6)
    assert metrics["candidate_recall_at"]["5"] == 1.0
    assert metrics["candidate_recall_at"]["10"] == 1.0

    detail = service.get(str(result["run_id"]), include_items=True, only_errors=True)
    assert len(detail["items"]) == 3
    assert {item["truth_key"] for item in detail["items"]} == {"B", "C", "X"}
    history = service.list_for_task("task-1")
    assert history[0]["run_id"] == result["run_id"]


def test_business_evaluation_rejects_conflicting_truth_labels(tmp_path: Path) -> None:
    meta = MetadataRepository(tmp_path / "data/meta/material_matcher.db")
    files = FileRepository(tmp_path / "data", meta)
    _seed_task(meta)
    record = files.save_stream(
        "truth.csv",
        "supplement",
        BytesIO("物料号,正确集团码\nA,G1\nA,G2\n".encode("utf-8")),
        1024 * 1024,
    )
    service = BusinessEvaluationService(meta, files)
    with pytest.raises(DomainError) as exc:
        service.evaluate(
            "task-1",
            truth_file_id=str(record["file_id"]),
            key_column="物料号",
            expected_group_code_column="正确集团码",
        )
    assert exc.value.code == "EVALUATION_LABEL_CONFLICT"


def test_business_evaluation_rejects_duplicate_task_source_ids(tmp_path: Path) -> None:
    meta = MetadataRepository(tmp_path / "data/meta/material_matcher.db")
    files = FileRepository(tmp_path / "data", meta)
    _seed_task(meta)
    now = "2026-09-15T19:00:00+08:00"
    with meta.connect() as connection:
        connection.execute(
            f"INSERT INTO match_items({_MATCH_ITEM_COLUMNS}) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("task-1", "row-4", "A", "{}", "MATCHED", "MATCHED", "G1", 95.0, 60.0, 35.0, 0, "G1", now, now),
        )
    service = BusinessEvaluationService(meta, files)
    with pytest.raises(DomainError) as exc:
        service.evaluate(
            "task-1",
            truth_file_id=_truth_file(files),
            key_column="物料号",
            expected_group_code_column="正确集团码",
        )
    assert exc.value.code == "EVALUATION_TASK_KEY_AMBIGUOUS"
