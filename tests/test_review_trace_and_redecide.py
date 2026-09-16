from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from material_matcher.settings import Settings
from material_matcher.storage.files import FileRepository
from material_matcher.storage.metadata import MetadataRepository
from material_matcher.services.match_service import MatchService


def _service(tmp_path: Path) -> tuple[MatchService, MetadataRepository]:
    settings = Settings(data_dir=tmp_path / "data", config_dir=tmp_path / "etc", log_dir=tmp_path / "log", admin_password="x")
    settings.ensure_dirs()
    meta = MetadataRepository(settings.data_dir / "meta" / "material_matcher.db")
    return MatchService(meta, FileRepository(settings.data_dir, meta), settings), meta


def _seed(tmp_path: Path, meta: MetadataRepository, rows: list[tuple[str, str, str, float]]) -> str:
    now = "2026-09-16T00:00:00"
    with meta.connect() as conn:
        icols = [r[1] for r in conn.execute("PRAGMA table_info(match_items)").fetchall()]
    task_values = {
        "task_id": "t-1", "name": "tr", "source_file_id": "f-s", "catalog_version_id": "c-1",
        "config_snapshot": "{}", "config_sha256": "sha", "stage": "REVIEW", "status": "COMPLETED",
        "progress": 100.0, "processed_rows": len(rows), "total_rows": len(rows),
        "created_at": now, "started_at": now, "finished_at": now,
    }
    with meta.connect() as conn:
        conn.execute(f"INSERT INTO tasks({','.join(task_values)}) VALUES({','.join('?' * len(task_values))})", list(task_values.values()))
        for rid, status, original, score in rows:
            vals = {
                "task_id": "t-1", "source_row_id": rid, "source_id": rid,
                "source_payload": "{}", "original_status": original, "current_status": status,
                "top1_group_code": "G1", "top1_score": score, "second_score": score - 1, "score_gap": 1.0,
                "critical_conflict": 0, "final_group_code": "G1" if status == "MATCHED" else None,
                "created_at": now, "updated_at": now,
            }
            keys = [k for k in icols if k in vals]
            conn.execute(f"INSERT INTO match_items({','.join(keys)}) VALUES({','.join('?' * len(keys))})", [vals[k] for k in keys])
            conn.execute(f"INSERT INTO match_candidates({','.join(['task_id','source_row_id','rank','target_group_code','target_payload','score','field_scores','critical_conflict'])}) VALUES(?,?,?,?,?,?,?,?)",
                         ("t-1", rid, 1, "G1", "{}", score, "[]", 0))
    return "t-1"


def test_review_operator_is_attributed_per_session(tmp_path: Path) -> None:
    service, meta = _service(tmp_path)
    _seed(tmp_path, meta, [("r1", "REVIEW", "REVIEW", 82.0)])
    service.confirm("t-1", "r1", "G1", "ok", operator="reviewer-王")
    with meta.connect() as conn:
        row = conn.execute("SELECT operator, action FROM reviews WHERE task_id='t-1' AND source_row_id='r1'").fetchone()
    assert str(row["operator"]) == "reviewer-王"
    assert str(row["action"]) == "CONFIRM_CANDIDATE"


def test_redecide_recovers_auto_unmatched_and_skips_human_rows(tmp_path: Path) -> None:
    service, meta = _service(tmp_path)
    _seed(tmp_path, meta, [
        ("r1", "UNMATCHED", "REVIEW", 66.0),   # 曾被收紧打下去,未被人工处理 → 放宽可回捞
        ("r2", "UNMATCHED", "UNMATCHED", 66.0),  # 完成时本就未匹配 → 原样也满足 55<66<70 → 变 REVIEW
        ("r3", "UNMATCHED", "REVIEW", 66.0),   # 人工处理过 → 不动
    ])
    with meta.connect() as conn:
        conn.execute("INSERT INTO reviews(review_id,task_id,source_row_id,original_status,selected_group_code,action,operator,comment,created_at) VALUES('x','t-1','r3','REVIEW',NULL,'REJECT_ALL','admin','人工',\\'2026-09-16T00:00:00')".replace("\\'", "'"))
    result = service.re_decide("t-1", 70, 55)
    assert result["before"]["unmatched"] == 2  # r1/r2 纯自动未匹配; r3 人工处理被排除
    with meta.connect() as conn:
        st_r1 = str(conn.execute("SELECT current_status FROM match_items WHERE source_row_id='r1'").fetchone()["current_status"])
        st_r1 = str(conn.execute("SELECT current_status FROM match_items WHERE source_row_id='r1'").fetchone()["current_status"])
        st_r2 = str(conn.execute("SELECT current_status FROM match_items WHERE source_row_id='r2'").fetchone()["current_status"])
        st_r3 = str(conn.execute("SELECT current_status FROM match_items WHERE source_row_id='r3'").fetchone()["current_status"])
        st_r2 = str(conn.execute("SELECT current_status FROM match_items WHERE source_row_id='r2'").fetchone()["current_status"])
    assert st_r1 == "REVIEW"
    assert st_r2 == "REVIEW"
    assert st_r3 == "UNMATCHED"
