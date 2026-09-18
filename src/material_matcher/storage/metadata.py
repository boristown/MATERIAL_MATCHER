from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from typing import Iterator, Sequence

SCHEMA = """
CREATE TABLE IF NOT EXISTS files(
  file_id TEXT PRIMARY KEY, role TEXT NOT NULL, original_name TEXT NOT NULL,
  stored_path TEXT NOT NULL, size_bytes INTEGER NOT NULL, sha256 TEXT NOT NULL,
  status TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS catalogs(
  catalog_id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS catalog_versions(
  version_id TEXT PRIMARY KEY, catalog_id TEXT NOT NULL, source_file_id TEXT NOT NULL,
  group_code_column TEXT NOT NULL, status TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  FOREIGN KEY(catalog_id) REFERENCES catalogs(catalog_id),
  FOREIGN KEY(source_file_id) REFERENCES files(file_id)
);
CREATE TABLE IF NOT EXISTS task_drafts(
  draft_id TEXT PRIMARY KEY, name TEXT NOT NULL, source_file_id TEXT,
  catalog_version_id TEXT, template_profile_id TEXT, template_profile_version INTEGER,
  config_document TEXT NOT NULL, current_step INTEGER NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks(
  task_id TEXT PRIMARY KEY, name TEXT NOT NULL, source_file_id TEXT NOT NULL,
  catalog_version_id TEXT NOT NULL, profile_id TEXT, profile_version INTEGER,
  config_snapshot TEXT NOT NULL, config_sha256 TEXT NOT NULL,
  stage TEXT NOT NULL, status TEXT NOT NULL, progress REAL NOT NULL,
  processed_rows INTEGER NOT NULL, total_rows INTEGER NOT NULL,
  created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
  error_code TEXT, error_message TEXT, result_file_id TEXT
);
CREATE TABLE IF NOT EXISTS task_actors(
  task_id TEXT PRIMARY KEY,
  created_by TEXT,
  started_by TEXT,
  FOREIGN KEY(task_id) REFERENCES tasks(task_id)
);
CREATE TABLE IF NOT EXISTS task_input_assets(
  task_id TEXT NOT NULL,
  asset_role TEXT NOT NULL,
  file_id TEXT NOT NULL,
  original_name TEXT NOT NULL,
  uploaded_at TEXT,
  frozen_at TEXT NOT NULL,
  catalog_version_id TEXT,
  PRIMARY KEY(task_id, asset_role),
  FOREIGN KEY(task_id) REFERENCES tasks(task_id),
  FOREIGN KEY(file_id) REFERENCES files(file_id)
);
CREATE INDEX IF NOT EXISTS idx_task_input_assets_file ON task_input_assets(file_id);
CREATE TABLE IF NOT EXISTS task_runtime(
  task_id TEXT PRIMARY KEY, execution_mode TEXT NOT NULL, current_phase TEXT NOT NULL,
  index_id TEXT, updated_at TEXT NOT NULL,
  FOREIGN KEY(task_id) REFERENCES tasks(task_id)
);
CREATE TABLE IF NOT EXISTS task_compute_lifecycle(
  task_id TEXT PRIMARY KEY,
  compute_started_at TEXT,
  compute_completed_at TEXT,
  FOREIGN KEY(task_id) REFERENCES tasks(task_id)
);
CREATE TABLE IF NOT EXISTS match_items(
  task_id TEXT NOT NULL, source_row_id TEXT NOT NULL, source_row_number INTEGER,
  source_id TEXT NOT NULL, source_payload TEXT NOT NULL,
  original_status TEXT NOT NULL, current_status TEXT NOT NULL,
  top1_group_code TEXT, top1_score REAL NOT NULL, second_score REAL NOT NULL,
  score_gap REAL NOT NULL, critical_conflict INTEGER NOT NULL, final_group_code TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  PRIMARY KEY(task_id, source_row_id),
  FOREIGN KEY(task_id) REFERENCES tasks(task_id)
);
CREATE INDEX IF NOT EXISTS idx_match_items_task_status_score ON match_items(task_id,current_status,top1_score);
CREATE TABLE IF NOT EXISTS match_candidates(
  task_id TEXT NOT NULL, source_row_id TEXT NOT NULL, rank INTEGER NOT NULL,
  target_row_number INTEGER, target_group_code TEXT NOT NULL, target_payload TEXT NOT NULL,
  score REAL NOT NULL, field_scores TEXT NOT NULL, critical_conflict INTEGER NOT NULL,
  PRIMARY KEY(task_id, source_row_id, rank),
  FOREIGN KEY(task_id, source_row_id) REFERENCES match_items(task_id, source_row_id)
);
CREATE TABLE IF NOT EXISTS upload_sessions(
  upload_id TEXT PRIMARY KEY, role TEXT NOT NULL, original_name TEXT NOT NULL,
  expected_size INTEGER NOT NULL, expected_sha256 TEXT, received_bytes INTEGER NOT NULL,
  next_chunk INTEGER NOT NULL, tmp_path TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions(
  token TEXT PRIMARY KEY, username TEXT NOT NULL, role TEXT NOT NULL,
  expires_at REAL NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews(
  review_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, source_row_id TEXT NOT NULL,
  original_status TEXT NOT NULL, selected_group_code TEXT, action TEXT NOT NULL,
  operator TEXT NOT NULL, comment TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reviews_task_item ON reviews(task_id,source_row_id);
CREATE TABLE IF NOT EXISTS decision_revisions(
  task_id TEXT NOT NULL,
  revision_no INTEGER NOT NULL,
  success_threshold REAL NOT NULL,
  review_threshold REAL NOT NULL,
  operator TEXT NOT NULL,
  before_counts TEXT NOT NULL,
  after_counts TEXT NOT NULL,
  transitions TEXT NOT NULL,
  rollback_of_revision INTEGER,
  created_at TEXT NOT NULL,
  PRIMARY KEY(task_id,revision_no),
  FOREIGN KEY(task_id) REFERENCES tasks(task_id)
);
CREATE INDEX IF NOT EXISTS idx_decision_revisions_task_created ON decision_revisions(task_id,created_at DESC);
CREATE TABLE IF NOT EXISTS result_revisions(
  task_id TEXT NOT NULL,
  revision_no INTEGER NOT NULL,
  decision_revision_no INTEGER NOT NULL,
  file_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(task_id,revision_no),
  UNIQUE(task_id,file_id),
  FOREIGN KEY(task_id) REFERENCES tasks(task_id),
  FOREIGN KEY(file_id) REFERENCES files(file_id)
);
CREATE INDEX IF NOT EXISTS idx_result_revisions_task_decision ON result_revisions(task_id,decision_revision_no,revision_no DESC);
CREATE TABLE IF NOT EXISTS match_operation_logs(
  operation_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  source_row_id TEXT NOT NULL,
  source_row_number INTEGER,
  operator TEXT NOT NULL,
  operated_at TEXT NOT NULL,
  operation_type TEXT NOT NULL,
  before_status TEXT NOT NULL,
  after_status TEXT NOT NULL,
  previous_group_code TEXT,
  selected_group_code TEXT,
  previous_target_row_number INTEGER,
  target_row_number INTEGER,
  source TEXT NOT NULL,
  comment TEXT NOT NULL DEFAULT '',
  FOREIGN KEY(task_id, source_row_id) REFERENCES match_items(task_id, source_row_id)
);
CREATE INDEX IF NOT EXISTS idx_match_operation_task_time ON match_operation_logs(task_id, operated_at DESC);
CREATE INDEX IF NOT EXISTS idx_match_operation_item_time ON match_operation_logs(task_id, source_row_id, operated_at DESC);
CREATE TABLE IF NOT EXISTS audit_events(
  event_id TEXT PRIMARY KEY, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
  action TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users(
  username TEXT PRIMARY KEY, password_hash TEXT NOT NULL, salt TEXT NOT NULL,
  role TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
  must_change_password INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_users_role_enabled ON users(role, enabled);
CREATE TABLE IF NOT EXISTS profiles(
  profile_id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profile_versions(
  profile_id TEXT NOT NULL, version_no INTEGER NOT NULL, document TEXT NOT NULL,
  sha256 TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY(profile_id, version_no)
);
CREATE TABLE IF NOT EXISTS dictionaries(
  dictionary_id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dictionary_versions(
  dictionary_id TEXT NOT NULL, version_no INTEGER NOT NULL, document TEXT NOT NULL,
  sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY(dictionary_id, version_no)
);
CREATE TABLE IF NOT EXISTS index_versions(
  index_id TEXT PRIMARY KEY, catalog_version_id TEXT NOT NULL, metadata TEXT NOT NULL,
  status TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_index_versions_catalog_status ON index_versions(catalog_version_id, status);
CREATE TABLE IF NOT EXISTS benchmark_runs(
  run_id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL,
  parameters TEXT NOT NULL, metrics TEXT NOT NULL, error_message TEXT,
  started_at TEXT NOT NULL, finished_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_benchmark_runs_started_at ON benchmark_runs(started_at DESC);
CREATE TABLE IF NOT EXISTS evaluation_runs(
  run_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, truth_file_id TEXT NOT NULL,
  key_mode TEXT NOT NULL, key_column TEXT NOT NULL, expected_column TEXT NOT NULL,
  expected_result_column TEXT,
  metrics TEXT NOT NULL, created_at TEXT NOT NULL,
  FOREIGN KEY(task_id) REFERENCES tasks(task_id),
  FOREIGN KEY(truth_file_id) REFERENCES files(file_id)
);
CREATE INDEX IF NOT EXISTS idx_evaluation_runs_task_created ON evaluation_runs(task_id, created_at DESC);
CREATE TABLE IF NOT EXISTS evaluation_items(
  run_id TEXT NOT NULL, truth_key TEXT NOT NULL, expected_result TEXT NOT NULL DEFAULT 'MATCH',
  expected_group_code TEXT NOT NULL,
  matched_task_row INTEGER NOT NULL, source_row_id TEXT, source_id TEXT,
  original_status TEXT, current_status TEXT, top1_group_code TEXT, final_group_code TEXT,
  top1_score REAL, top1_correct INTEGER NOT NULL, final_correct INTEGER NOT NULL,
  expected_candidate_rank INTEGER,
  PRIMARY KEY(run_id, truth_key),
  FOREIGN KEY(run_id) REFERENCES evaluation_runs(run_id)
);
CREATE INDEX IF NOT EXISTS idx_evaluation_items_errors ON evaluation_items(run_id, final_correct, top1_correct);
"""


class MetadataRepository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def initialize(self) -> None:
        with self.connect() as connection:
            # Detect the one-time lifecycle migration before SCHEMA creates the
            # table. Existing tasks used started_at=worker-claim time and
            # finished_at=automatic matching completion time.
            had_compute_lifecycle = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_compute_lifecycle'"
            ).fetchone() is not None
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(SCHEMA)
            if not had_compute_lifecycle:
                # The pre-migration pair is reliable only for completed automatic
                # runs. Preserve it as the immutable compute window, then restore
                # started_at to its business meaning: the click-to-start time,
                # which was historically stored in created_at.
                connection.execute(
                    """INSERT OR IGNORE INTO task_compute_lifecycle(
                           task_id,compute_started_at,compute_completed_at
                       )
                       SELECT task_id,started_at,finished_at
                       FROM tasks
                       WHERE status='COMPLETED'
                         AND started_at IS NOT NULL
                         AND finished_at IS NOT NULL"""
                )
                connection.execute(
                    "UPDATE tasks SET started_at=created_at WHERE created_at IS NOT NULL"
                )
            # Forward-compatible migrations for deployments created before source /
            # target original-row traceability and calibration revisions existed.
            self._ensure_column(connection, "match_items", "source_row_number", "INTEGER")
            self._ensure_column(connection, "match_candidates", "target_row_number", "INTEGER")
            self._ensure_column(connection, "evaluation_runs", "expected_result_column", "TEXT")
            self._ensure_column(connection, "evaluation_items", "expected_result", "TEXT NOT NULL DEFAULT 'MATCH'")
            self._ensure_column(connection, "dictionary_versions", "created_by", "TEXT NOT NULL DEFAULT ''")
            connection.execute("UPDATE tasks SET status='RECOVERING' WHERE status IN ('RUNNING','PREPARING','EXPORTING')")
            connection.execute("UPDATE task_runtime SET current_phase='RECOVERING', updated_at=datetime('now') WHERE task_id IN (SELECT task_id FROM tasks WHERE status='RECOVERING')")

    @staticmethod
    def decode(row: sqlite3.Row | None, json_fields: Sequence[str] = ()) -> dict[str, object] | None:
        if row is None:
            return None
        result: dict[str, object] = dict(row)
        for key in json_fields:
            if result.get(key):
                result[key] = json.loads(str(result[key]))
        return result
