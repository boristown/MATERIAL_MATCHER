from __future__ import annotations

import json
from pathlib import Path

from material_matcher.services.acceptance_service import AcceptanceService
from material_matcher.settings import Settings
from material_matcher.storage.metadata import MetadataRepository


def test_acceptance_prefers_current_calibrated_review_rate(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "etc",
        log_dir=tmp_path / "log",
        admin_password="x",
        worker_enabled=False,
        acceptance_min_truth_rows=100,
        acceptance_min_truth_coverage=0.95,
        acceptance_min_top1_accuracy=0.85,
        acceptance_min_final_accuracy=0.95,
        acceptance_max_review_rate=0.20,
        acceptance_min_candidate_recall_at_5=0.95,
        acceptance_min_automatic_precision=0.98,
        acceptance_max_no_match_false_positive_rate=0.02,
        acceptance_max_scale_hours=2.0,
    )
    settings.ensure_dirs()
    meta = MetadataRepository(settings.metadata_db_path)
    now = "2026-09-17T13:00:00+08:00"
    metrics = {
        "truth_rows": 500,
        "truth_coverage": 0.99,
        "top1_accuracy": 0.90,
        "candidate_recall_at_5": 0.97,
        "automatic_match_precision": 0.99,
        "final_accuracy": 0.98,
        # Legacy/baseline review rate would pass, but the calibrated current
        # decision now sends too many rows to review and must fail acceptance.
        "review_rate": 0.10,
        "current_review_rate": 0.30,
        "no_match_false_positive_rate": 0.01,
    }
    with meta.connect() as connection:
        connection.execute(
            "INSERT INTO files(file_id,role,original_name,stored_path,size_bytes,sha256,status,created_at) VALUES(?,?,?,?,?,?,?,?)",
            ("truth", "supplement", "truth.csv", "/tmp/truth.csv", 1, "sha", "READY", now),
        )
        connection.execute(
            """INSERT INTO tasks(
               task_id,name,source_file_id,catalog_version_id,config_snapshot,config_sha256,
               stage,status,progress,processed_rows,total_rows,created_at,started_at,finished_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("task", "验收", "source", "catalog", "{}", "sha", "RESULT", "COMPLETED", 100.0, 500, 500, now, now, now),
        )
        connection.execute(
            """INSERT INTO evaluation_runs(
               run_id,task_id,truth_file_id,key_mode,key_column,expected_column,metrics,created_at
               ) VALUES(?,?,?,?,?,?,?,?)""",
            ("eval", "task", "truth", "source_id", "物料号", "集团码", json.dumps(metrics), now),
        )

    gate = AcceptanceService(meta, settings)._business_evaluation_gate(policy_ready=True)
    assert gate["status"] == "FAIL"
    assert gate["evidence"]["checks"]["review_rate"] is False
    assert gate["evidence"]["effective_review_rate"] == 0.30
