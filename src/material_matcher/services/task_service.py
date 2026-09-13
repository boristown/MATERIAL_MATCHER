from __future__ import annotations

from datetime import datetime
import hashlib
import json
from typing import Any
import uuid

from material_matcher.domain.errors import DomainError
from material_matcher.domain.models import MatchingConfig
from material_matcher.storage.metadata import MetadataRepository


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class TaskService:
    def __init__(self, repository: MetadataRepository) -> None:
        self.repo = repository

    def create_draft(self, name: str) -> dict[str, object]:
        draft_id = uuid.uuid4().hex
        created_at = _now()
        with self.repo.connect() as connection:
            connection.execute(
                "INSERT INTO task_drafts VALUES(?,?,?,?,?,?,?,?,?,?)",
                (draft_id, name, None, None, None, None, "{}", 1, created_at, created_at),
            )
        return self.get_draft(draft_id)

    def list_drafts(self) -> list[dict[str, object]]:
        with self.repo.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM task_drafts ORDER BY updated_at DESC"
            ).fetchall()
        return [self.repo.decode(row, ("config_document",)) or {} for row in rows]

    def get_draft(self, draft_id: str) -> dict[str, object]:
        with self.repo.connect() as connection:
            row = connection.execute(
                "SELECT * FROM task_drafts WHERE draft_id=?", (draft_id,)
            ).fetchone()
        if row is None:
            raise DomainError(
                "TASK_DRAFT_NOT_FOUND", "任务草稿不存在", status_code=404
            )
        return self.repo.decode(row, ("config_document",)) or {}

    def save_data(self, draft_id: str, payload: dict[str, Any]) -> dict[str, object]:
        self.get_draft(draft_id)
        with self.repo.connect() as connection:
            connection.execute(
                """
                UPDATE task_drafts
                   SET source_file_id=?, catalog_version_id=?, template_profile_id=?,
                       template_profile_version=?, current_step=2, updated_at=?
                 WHERE draft_id=?
                """,
                (
                    payload.get("source_file_id"),
                    payload.get("catalog_version_id"),
                    payload.get("template_profile_id"),
                    payload.get("template_profile_version"),
                    _now(),
                    draft_id,
                ),
            )
        return self.get_draft(draft_id)

    def save_rules(self, draft_id: str, document: dict[str, Any]) -> dict[str, object]:
        self.get_draft(draft_id)
        MatchingConfig.model_validate(document)
        with self.repo.connect() as connection:
            connection.execute(
                """
                UPDATE task_drafts
                   SET config_document=?, current_step=2, updated_at=?
                 WHERE draft_id=?
                """,
                (_canonical(document), _now(), draft_id),
            )
        return self.get_draft(draft_id)

    def start(self, draft_id: str) -> dict[str, object]:
        draft = self.get_draft(draft_id)
        if not draft.get("source_file_id") or not draft.get("catalog_version_id"):
            raise DomainError(
                "TASK_DRAFT_INCOMPLETE",
                "请先选择客户物料数据和集团码目录",
                status_code=422,
            )

        config = MatchingConfig.model_validate(draft.get("config_document") or {})
        if not config.rules:
            raise DomainError(
                "INVALID_PROFILE",
                "至少配置一条字段对应关系后才能开始比对",
                status_code=422,
            )

        snapshot = config.model_dump(mode="json")
        encoded_snapshot = _canonical(snapshot)
        snapshot_sha256 = hashlib.sha256(encoded_snapshot.encode("utf-8")).hexdigest()
        task_id = uuid.uuid4().hex
        created_at = _now()
        with self.repo.connect() as connection:
            connection.execute(
                "INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    task_id,
                    draft["name"],
                    draft["source_file_id"],
                    draft["catalog_version_id"],
                    draft.get("template_profile_id"),
                    draft.get("template_profile_version"),
                    encoded_snapshot,
                    snapshot_sha256,
                    "CALCULATE",
                    "PENDING",
                    0.0,
                    0,
                    0,
                    created_at,
                    None,
                    None,
                    None,
                    None,
                    None,
                ),
            )
            connection.execute(
                "INSERT INTO audit_events VALUES(?,?,?,?,?,?)",
                (
                    uuid.uuid4().hex,
                    "task",
                    task_id,
                    "CONFIG_SNAPSHOT_FROZEN",
                    _canonical({"config_sha256": snapshot_sha256}),
                    created_at,
                ),
            )
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> dict[str, object]:
        with self.repo.connect() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
        if row is None:
            raise DomainError("TASK_NOT_FOUND", "任务不存在", status_code=404)
        return self.repo.decode(row, ("config_snapshot",)) or {}

    def list_tasks(self) -> list[dict[str, object]]:
        with self.repo.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC"
            ).fetchall()
        return [self.repo.decode(row, ("config_snapshot",)) or {} for row in rows]
