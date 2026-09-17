from __future__ import annotations

from io import BytesIO
from pathlib import Path
import time

from material_matcher.services.decision_calibration_service import DecisionCalibrationService
from material_matcher.services.versioned_result_service import VersionedResultService
from material_matcher.settings import Settings
from material_matcher.storage.files import FileRepository
from material_matcher.storage.metadata import MetadataRepository


_ITEM_COLUMNS = "task_id,source_row_id,source_id,source_payload,original_status,current_status,top1_group_code,top1_score,second_score,score_gap,critical_conflict,final_group_code,created_at,updated_at"
_CANDIDATE_COLUMNS = "task_id,source_row_id,rank,target_group_code,target_payload,score,field_scores,critical_conflict"


def _environment(tmp_path: Path) -> tuple[DecisionCalibrationService, MetadataRepository, FileRepository, Settings]:
    settings = Settings(
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "etc",
        log_dir=tmp_path / "log",
        admin_password="x",
        worker_enabled=False,
    )
    settings.ensure_dirs()
    meta = MetadataRepository(settings.metadata_db_path)
    files = FileRepository(settings.data_dir, meta)
    return DecisionCalibrationService(meta), meta, files, settings


def _insert_task(meta: MetadataRepository, *, task_id: str = "task-1", result_file_id: str | None = None, total: int = 5) -> None:
    now = "2026-09-17T12:00:00+08:00"
    with meta.connect() as connection:
        connection.execute(
            """INSERT INTO tasks(
               task_id,name,source_file_id,catalog_version_id,config_snapshot,config_sha256,
               stage,status,progress,processed_rows,total_rows,created_at,started_at,finished_at,result_file_id
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                task_id,
                "阈值验收",
                "source",
                "catalog",
                '{"decision":{"success_threshold":78,"review_threshold":60,"top_n":10}}',
                "sha",
                "RESULT",
                "COMPLETED",
                100.0,
                total,
                total,
                now,
                now,
                now,
                result_file_id,
            ),
        )


def _seed_small(meta: MetadataRepository) -> None:
    _insert_task(meta)
    now = "2026-09-17T12:00:00+08:00"
    rows = [
        ("task-1", "r1", "r1", "{}", "MATCHED", "MATCHED", "G1", 80.0, 70.0, 10.0, 0, "G1", now, now),
        ("task-1", "r2", "r2", "{}", "REVIEW", "REVIEW", "G2", 70.0, 60.0, 10.0, 0, None, now, now),
        ("task-1", "r3", "r3", "{}", "UNMATCHED", "UNMATCHED", "G3", 55.0, 40.0, 15.0, 0, None, now, now),
        ("task-1", "r4", "r4", "{}", "REVIEW", "CONFIRMED", "G4", 68.0, 60.0, 8.0, 0, "G4", now, now),
        ("task-1", "r5", "r5", "{}", "REVIEW", "UNMATCHED", "G5", 68.0, 60.0, 8.0, 0, None, now, now),
    ]
    with meta.connect() as connection:
        connection.executemany(f"INSERT INTO match_items({_ITEM_COLUMNS}) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        connection.executemany(
            f"INSERT INTO match_candidates({_CANDIDATE_COLUMNS}) VALUES(?,?,?,?,?,?,?,?)",
            [("task-1", rid, 1, code, "{}", score, "[]", 0) for rid, code, score in (
                ("r1", "G1", 80.0), ("r2", "G2", 70.0), ("r3", "G3", 55.0), ("r4", "G4", 68.0), ("r5", "G5", 68.0)
            )],
        )
        connection.execute(
            "INSERT INTO reviews VALUES(?,?,?,?,?,?,?,?,?)",
            ("review-r4", "task-1", "r4", "REVIEW", "G4", "CONFIRM_CANDIDATE", "alice", "", now),
        )
        connection.execute(
            "INSERT INTO reviews VALUES(?,?,?,?,?,?,?,?,?)",
            ("review-r5", "task-1", "r5", "REVIEW", None, "REJECT_ALL", "bob", "", now),
        )


def test_dual_threshold_preview_apply_revision_rollback_and_human_protection(tmp_path: Path) -> None:
    service, meta, _, _ = _environment(tmp_path)
    _seed_small(meta)

    preview = service.preview("task-1", 85, 45)
    assert preview["before"] == {"matched": 1, "review": 1, "unmatched": 2, "confirmed": 1}
    assert preview["after"] == {"matched": 0, "review": 3, "unmatched": 1, "confirmed": 1}
    assert preview["transitions"]["MATCHED->REVIEW"] == 1
    assert preview["transitions"]["REVIEW->REVIEW"] == 1
    assert preview["transitions"]["UNMATCHED->REVIEW"] == 1
    assert preview["human_protected"] == 2

    applied = service.apply("task-1", 65, 45, operator="calibrator")
    assert applied["revision_no"] == 1
    with meta.connect() as connection:
        states = {row["source_row_id"]: row["current_status"] for row in connection.execute(
            "SELECT source_row_id,current_status FROM match_items WHERE task_id='task-1'"
        ).fetchall()}
    assert states == {"r1": "MATCHED", "r2": "MATCHED", "r3": "REVIEW", "r4": "CONFIRMED", "r5": "UNMATCHED"}

    second = service.apply("task-1", 90, 75, operator="calibrator")
    assert second["revision_no"] == 2
    rolled = service.rollback("task-1", 1, operator="admin")
    assert rolled["revision_no"] == 3
    revisions = service.revisions("task-1")
    assert [row["revision_no"] for row in revisions] == [3, 2, 1]
    assert revisions[0]["rollback_of_revision"] == 1
    assert revisions[0]["operator"] == "admin"
    assert revisions[0]["success_threshold"] == 65.0
    assert revisions[0]["review_threshold"] == 45.0


def test_histograms_and_batch_preview_are_database_aggregations(tmp_path: Path) -> None:
    service, meta, _, _ = _environment(tmp_path)
    _insert_task(meta, total=6)
    now = "2026-09-17T12:00:00+08:00"
    scores = [5.0, 15.0, 25.0, 65.0, 85.0, 100.0]
    with meta.connect() as connection:
        connection.executemany(
            f"INSERT INTO match_items({_ITEM_COLUMNS}) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                ("task-1", str(i), str(i), "{}", "REVIEW", "REVIEW", f"G{i}", score, max(0, score - i), min(100, float(i)), 0, None, now, now)
                for i, score in enumerate(scores, start=1)
            ],
        )
    stats = service.statistics("task-1")
    assert [bucket["count"] for bucket in stats["top1_score_histogram"]] == [1, 1, 1, 0, 0, 0, 1, 0, 1, 1]
    assert len(stats["top1_top2_gap_histogram"]) == 10
    assert stats["counts"]["review"] == 6

    batch = service.batch_preview("task-1", [
        {"success_threshold": success, "review_threshold": max(0, success - 25)}
        for success in (95, 90, 85, 80, 75, 70, 65, 60)
    ])
    assert len(batch["scenarios"]) == 8
    assert all("transitions" in scenario for scenario in batch["scenarios"])


def test_existing_formal_result_is_preserved_and_new_decision_gets_result_v2(tmp_path: Path) -> None:
    service, meta, files, settings = _environment(tmp_path)
    old = files.save_stream("result-v1.xlsx", "result", BytesIO(b"old-result"), 1024 * 1024)
    _insert_task(meta, result_file_id=str(old["file_id"]), total=1)
    now = "2026-09-17T12:00:00+08:00"
    with meta.connect() as connection:
        connection.execute(
            f"INSERT INTO match_items({_ITEM_COLUMNS}) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("task-1", "r1", "r1", "{}", "MATCHED", "MATCHED", "G1", 90.0, 50.0, 40.0, 0, "G1", now, now),
        )
        connection.execute(
            f"INSERT INTO match_candidates({_CANDIDATE_COLUMNS}) VALUES(?,?,?,?,?,?,?,?)",
            ("task-1", "r1", 1, "G1", "{}", 90.0, "[]", 0),
        )

    service.apply("task-1", 80, 50, operator="alice")
    before_finalize = service.result_revisions("task-1")
    assert len(before_finalize) == 1
    assert before_finalize[0]["file_id"] == old["file_id"]
    assert before_finalize[0]["decision_revision_no"] == 0

    generated = VersionedResultService(meta, files, settings).finalize("task-1")
    assert generated["result_revision"] == 2
    assert generated["decision_revision"] == 1
    assert generated["result_file_id"] != old["file_id"]
    revisions = service.result_revisions("task-1")
    assert [row["revision_no"] for row in revisions] == [2, 1]
    assert files.get(str(old["file_id"]))["file_id"] == old["file_id"]


def test_100k_statistics_and_batch_preview_do_not_materialize_python_rows(tmp_path: Path) -> None:
    service, meta, _, _ = _environment(tmp_path)
    total = 100_000
    _insert_task(meta, task_id="task-big", total=total)
    now = "2026-09-17T12:00:00+08:00"
    with meta.connect() as connection:
        connection.executemany(
            f"INSERT INTO match_items({_ITEM_COLUMNS}) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                (
                    "task-big", str(i), str(i), "{}", "REVIEW", "REVIEW", f"G{i}",
                    float(i % 101), float(max(0, (i % 101) - 3)), 3.0, 0, None, now, now,
                )
                for i in range(total)
            ),
        )

    started = time.perf_counter()
    stats = service.statistics("task-big")
    preview = service.batch_preview("task-big", [
        {"success_threshold": success, "review_threshold": max(0, success - 20)}
        for success in (95, 90, 85, 80, 75, 70, 65, 60)
    ])
    elapsed = time.perf_counter() - started

    assert sum(bucket["count"] for bucket in stats["top1_score_histogram"]) == total
    assert stats["counts"]["review"] == total
    assert len(preview["scenarios"]) == 8
    # Deliberately generous for shared CI; a Python per-row/per-scenario loop is
    # materially slower and would also allocate the full 100k-row result set.
    assert elapsed < 8.0
