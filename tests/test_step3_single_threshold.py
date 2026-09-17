from __future__ import annotations

from pathlib import Path

from material_matcher.services.decision_calibration_service import DecisionCalibrationService
from material_matcher.settings import Settings
from material_matcher.storage.metadata import MetadataRepository


_ITEM_COLUMNS = "task_id,source_row_id,source_id,source_payload,original_status,current_status,top1_group_code,top1_score,second_score,score_gap,critical_conflict,final_group_code,created_at,updated_at"
_CANDIDATE_COLUMNS = "task_id,source_row_id,rank,target_group_code,target_payload,score,field_scores,critical_conflict"


def _environment(tmp_path: Path) -> tuple[DecisionCalibrationService, MetadataRepository]:
    settings = Settings(
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "etc",
        log_dir=tmp_path / "log",
        admin_password="x",
        worker_enabled=False,
    )
    settings.ensure_dirs()
    meta = MetadataRepository(settings.metadata_db_path)
    return DecisionCalibrationService(meta), meta


def _seed(meta: MetadataRepository) -> None:
    now = "2026-09-17T16:00:00+08:00"
    with meta.connect() as connection:
        connection.execute(
            """INSERT INTO tasks(
               task_id,name,source_file_id,catalog_version_id,config_snapshot,config_sha256,
               stage,status,progress,processed_rows,total_rows,created_at,started_at,finished_at,result_file_id
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "task-step3",
                "STEP3 单阈值验收",
                "source",
                "catalog",
                '{"decision":{"success_threshold":78,"review_threshold":60,"top_n":10}}',
                "sha",
                "RESULT",
                "COMPLETED",
                100.0,
                5,
                5,
                now,
                now,
                now,
                None,
            ),
        )
        rows = [
            ("task-step3", "auto", "auto", "{}", "MATCHED", "MATCHED", "G-AUTO", 72.0, 70.0, 2.0, 0, "G-AUTO", now, now),
            ("task-step3", "low-positive", "low-positive", "{}", "UNMATCHED", "UNMATCHED", "G-LOW", 12.0, 5.0, 7.0, 0, None, now, now),
            ("task-step3", "no-candidate", "no-candidate", "{}", "UNMATCHED", "UNMATCHED", None, 0.0, 0.0, 0.0, 0, None, now, now),
            ("task-step3", "human-confirmed", "human-confirmed", "{}", "REVIEW", "CONFIRMED", "G-HUMAN", 20.0, 10.0, 10.0, 0, "G-HUMAN", now, now),
            ("task-step3", "human-unmatched", "human-unmatched", "{}", "REVIEW", "UNMATCHED", "G-REJECT", 20.0, 10.0, 10.0, 0, None, now, now),
        ]
        connection.executemany(
            f"INSERT INTO match_items({_ITEM_COLUMNS}) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        connection.executemany(
            f"INSERT INTO match_candidates({_CANDIDATE_COLUMNS}) VALUES(?,?,?,?,?,?,?,?)",
            [
                ("task-step3", "auto", 1, "G-AUTO", '{"name":"自动候选"}', 72.0, "[]", 0),
                ("task-step3", "low-positive", 1, "G-LOW", '{"name":"低分候选"}', 12.0, "[]", 0),
                ("task-step3", "human-confirmed", 1, "G-HUMAN", '{"name":"人工确认"}', 20.0, "[]", 0),
                ("task-step3", "human-unmatched", 1, "G-REJECT", '{"name":"人工拒绝"}', 20.0, "[]", 0),
            ],
        )
        connection.execute(
            "INSERT INTO reviews VALUES(?,?,?,?,?,?,?,?,?)",
            ("review-confirmed", "task-step3", "human-confirmed", "REVIEW", "G-HUMAN", "CONFIRM_CANDIDATE", "alice", "", now),
        )
        connection.execute(
            "INSERT INTO reviews VALUES(?,?,?,?,?,?,?,?,?)",
            ("review-unmatched", "task-step3", "human-unmatched", "REVIEW", None, "REJECT_ALL", "bob", "", now),
        )


def test_step3_single_threshold_routes_positive_candidates_to_review_and_protects_human_results(tmp_path: Path) -> None:
    service, meta = _environment(tmp_path)
    _seed(meta)

    # Historical dual-threshold behavior stays strict: score == 72 is not an
    # automatic match when callers do not opt into STEP3 single-threshold mode.
    legacy_preview = service.preview("task-step3", 72, 0)
    assert legacy_preview["after"] == {"matched": 0, "review": 2, "unmatched": 2, "confirmed": 1}
    assert legacy_preview["single_threshold"] is False

    # STEP3's new mode implements the visible business rule exactly:
    # score >= automatic threshold => MATCHED; lower positive scores => REVIEW.
    preview = service.re_decide(
        "task-step3",
        72,
        60,
        "preview",
        operator="step3-ui",
        single_threshold=True,
    )
    assert preview["before"] == {"matched": 1, "review": 0, "unmatched": 3, "confirmed": 1}
    assert preview["after"] == {"matched": 1, "review": 1, "unmatched": 2, "confirmed": 1}
    assert preview["transitions"]["MATCHED->MATCHED"] == 1
    assert preview["transitions"]["UNMATCHED->REVIEW"] == 1
    assert preview["human_protected"] == 2
    assert preview["review_threshold"] == 0.0
    assert preview["single_threshold"] is True

    applied = service.re_decide(
        "task-step3",
        72,
        60,
        "apply",
        operator="step3-ui",
        single_threshold=True,
    )
    assert applied["revision_no"] == 1
    assert applied["single_threshold"] is True

    with meta.connect() as connection:
        states = {
            row["source_row_id"]: row["current_status"]
            for row in connection.execute(
                "SELECT source_row_id,current_status FROM match_items WHERE task_id=?",
                ("task-step3",),
            ).fetchall()
        }

    assert states == {
        "auto": "MATCHED",
        "low-positive": "REVIEW",
        "no-candidate": "UNMATCHED",
        "human-confirmed": "CONFIRMED",
        "human-unmatched": "UNMATCHED",
    }

    revision = service.revisions("task-step3")[0]
    assert revision["success_threshold"] == 72.0
    assert revision["review_threshold"] == 0.0
    assert revision["operator"] == "step3-ui"
