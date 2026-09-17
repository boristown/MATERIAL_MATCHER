from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from material_matcher.domain.errors import DomainError
from material_matcher.services.business_evaluation_service import BusinessEvaluationService
from material_matcher.storage.files import FileRepository
from material_matcher.storage.metadata import MetadataRepository


_ITEM_COLUMNS = "task_id,source_row_id,source_id,source_payload,original_status,current_status,top1_group_code,top1_score,second_score,score_gap,critical_conflict,final_group_code,created_at,updated_at"
_CANDIDATE_COLUMNS = "task_id,source_row_id,rank,target_group_code,target_payload,score,field_scores,critical_conflict"


def _seed(meta: MetadataRepository) -> None:
    now = "2026-09-17T12:00:00+08:00"
    with meta.connect() as connection:
        connection.execute(
            "INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("task-1", "NO_MATCH验收", "source", "catalog", None, None, '{"decision":{"top_n":10}}', "sha", "RESULT", "COMPLETED", 100.0, 4, 4, now, now, now, None, None, None),
        )
        connection.executemany(
            f"INSERT INTO match_items({_ITEM_COLUMNS}) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                ("task-1", "r1", "A", "{}", "MATCHED", "MATCHED", "G1", 98.0, 60.0, 38.0, 0, "G1", now, now),
                ("task-1", "r2", "B", "{}", "REVIEW", "REVIEW", "G9", 80.0, 78.0, 2.0, 0, None, now, now),
                ("task-1", "r3", "C", "{}", "UNMATCHED", "UNMATCHED", "G8", 30.0, 20.0, 10.0, 0, None, now, now),
                ("task-1", "r4", "D", "{}", "MATCHED", "MATCHED", "G7", 92.0, 50.0, 42.0, 0, "G7", now, now),
            ],
        )
        connection.executemany(
            f"INSERT INTO match_candidates({_CANDIDATE_COLUMNS}) VALUES(?,?,?,?,?,?,?,?)",
            [
                ("task-1", "r1", 1, "G1", "{}", 98.0, "[]", 0),
                ("task-1", "r2", 1, "G9", "{}", 80.0, "[]", 0),
                ("task-1", "r2", 2, "G2", "{}", 78.0, "[]", 0),
                ("task-1", "r3", 1, "G8", "{}", 30.0, "[]", 0),
                ("task-1", "r4", 1, "G7", "{}", 92.0, "[]", 0),
            ],
        )


def test_explicit_no_match_truth_metrics(tmp_path: Path) -> None:
    meta = MetadataRepository(tmp_path / "data/meta/material_matcher.db")
    files = FileRepository(tmp_path / "data", meta)
    _seed(meta)
    truth = files.save_stream(
        "truth.csv",
        "supplement",
        BytesIO(
            "物料号,expected_result,expected_group_code\n"
            "A,MATCH,G1\n"
            "B,MATCH,G2\n"
            "C,NO_MATCH,\n"
            "D,NO_MATCH,\n".encode("utf-8")
        ),
        1024 * 1024,
    )

    result = BusinessEvaluationService(meta, files).evaluate(
        "task-1",
        truth_file_id=str(truth["file_id"]),
        key_column="物料号",
        expected_group_code_column="expected_group_code",
        expected_result_column="expected_result",
    )
    metrics = result["metrics"]
    assert metrics["truth_coverage"] == 1.0
    assert metrics["positive_top1_accuracy"] == 0.5
    assert metrics["candidate_recall_at_5"] == 1.0
    assert metrics["candidate_recall_at_10"] == 1.0
    assert metrics["automatic_match_precision"] == 0.5
    assert metrics["final_accuracy"] == 0.5
    assert metrics["review_rate"] == 0.25
    assert metrics["no_match_true_negative_rate"] == 0.5
    assert metrics["no_match_false_positive_rate"] == 0.5

    detail = BusinessEvaluationService(meta, files).get(str(result["run_id"]), include_items=True)
    labels = {row["truth_key"]: (row["expected_result"], row["expected_group_code"]) for row in detail["items"]}
    assert labels["C"] == ("NO_MATCH", "")
    assert labels["D"] == ("NO_MATCH", "")


def test_blank_group_code_is_not_implicitly_no_match_in_legacy_truth(tmp_path: Path) -> None:
    meta = MetadataRepository(tmp_path / "data/meta/material_matcher.db")
    files = FileRepository(tmp_path / "data", meta)
    _seed(meta)
    truth = files.save_stream(
        "legacy.csv",
        "supplement",
        BytesIO("物料号,正确集团码\nA,G1\nC,\n".encode("utf-8")),
        1024 * 1024,
    )
    with pytest.raises(DomainError) as exc:
        BusinessEvaluationService(meta, files).evaluate(
            "task-1",
            truth_file_id=str(truth["file_id"]),
            key_column="物料号",
            expected_group_code_column="正确集团码",
        )
    assert exc.value.code == "EVALUATION_LABEL_INCOMPLETE"


def test_legacy_truth_with_nonempty_group_codes_remains_supported(tmp_path: Path) -> None:
    meta = MetadataRepository(tmp_path / "data/meta/material_matcher.db")
    files = FileRepository(tmp_path / "data", meta)
    _seed(meta)
    truth = files.save_stream(
        "legacy.csv",
        "supplement",
        BytesIO("物料号,正确集团码\nA,G1\nB,G2\n".encode("utf-8")),
        1024 * 1024,
    )
    result = BusinessEvaluationService(meta, files).evaluate(
        "task-1",
        truth_file_id=str(truth["file_id"]),
        key_column="物料号",
        expected_group_code_column="正确集团码",
    )
    assert result["metrics"]["positive_truth_rows"] == 2
    assert result["metrics"]["no_match_truth_rows"] == 0
    assert result["metrics"]["no_match_false_positive_rate"] is None


def test_explicit_no_match_rejects_nonempty_group_code(tmp_path: Path) -> None:
    meta = MetadataRepository(tmp_path / "data/meta/material_matcher.db")
    files = FileRepository(tmp_path / "data", meta)
    _seed(meta)
    truth = files.save_stream(
        "bad.csv",
        "supplement",
        BytesIO("物料号,expected_result,expected_group_code\nC,NO_MATCH,G3\n".encode("utf-8")),
        1024 * 1024,
    )
    with pytest.raises(DomainError) as exc:
        BusinessEvaluationService(meta, files).evaluate(
            "task-1",
            truth_file_id=str(truth["file_id"]),
            key_column="物料号",
            expected_group_code_column="expected_group_code",
            expected_result_column="expected_result",
        )
    assert exc.value.code == "EVALUATION_NO_MATCH_HAS_GROUP_CODE"
