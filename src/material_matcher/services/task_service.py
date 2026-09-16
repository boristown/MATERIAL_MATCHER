from __future__ import annotations

from datetime import datetime
import hashlib
import json
from typing import Any
import uuid

from material_matcher.domain.errors import DomainError
from material_matcher.domain.models import MatchingConfig
from material_matcher.services.dictionary_service import DictionaryService
from material_matcher.storage.metadata import MetadataRepository


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class TaskService:
    def __init__(self, repository: MetadataRepository) -> None:
        self.repo = repository
        self.dictionaries = DictionaryService(repository)

    def _validate_template_source(self, profile_id: str, version_no: int) -> None:
        with self.repo.connect() as connection:
            row = connection.execute(
                "SELECT status FROM profile_versions WHERE profile_id=? AND version_no=?",
                (profile_id, version_no),
            ).fetchone()
        if row is None or str(row["status"]) != "PUBLISHED":
            raise DomainError(
                "PROFILE_VERSION_NOT_FOUND",
                "任务引用的匹配方案发布版本不存在",
                status_code=422,
                details={"profile_id": profile_id, "version_no": version_no},
            )

    def create_draft(
        self,
        name: str,
        *,
        template_profile_id: str | None = None,
        template_profile_version: int | None = None,
        config_document: dict[str, Any] | None = None,
    ) -> dict[str, object]:
        draft_id = uuid.uuid4().hex
        created_at = _now()
        document = self.dictionaries.bind_references(config_document) if config_document is not None else {}
        if config_document is not None:
            MatchingConfig.model_validate(document)
        if template_profile_id is not None or template_profile_version is not None:
            if template_profile_id is None or template_profile_version is None:
                raise DomainError("PROFILE_VERSION_NOT_FOUND", "匹配方案来源必须同时包含方案和版本", status_code=422)
            self._validate_template_source(str(template_profile_id), int(template_profile_version))
        with self.repo.connect() as connection:
            connection.execute(
                "INSERT INTO task_drafts VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    draft_id,
                    name,
                    None,
                    None,
                    template_profile_id,
                    template_profile_version,
                    _canonical(document),
                    1,
                    created_at,
                    created_at,
                ),
            )
            if template_profile_id is not None and template_profile_version is not None:
                connection.execute(
                    "INSERT INTO audit_events VALUES(?,?,?,?,?,?)",
                    (
                        uuid.uuid4().hex,
                        "task_draft",
                        draft_id,
                        "PROFILE_TEMPLATE_APPLIED",
                        _canonical({"profile_id": template_profile_id, "version_no": template_profile_version}),
                        created_at,
                    ),
                )
        return self.get_draft(draft_id)

    def list_drafts(self) -> list[dict[str, object]]:
        with self.repo.connect() as connection:
            rows = connection.execute("SELECT * FROM task_drafts ORDER BY updated_at DESC").fetchall()
        return [self.repo.decode(row, ("config_document",)) or {} for row in rows]

    def get_draft(self, draft_id: str) -> dict[str, object]:
        with self.repo.connect() as connection:
            row = connection.execute("SELECT * FROM task_drafts WHERE draft_id=?", (draft_id,)).fetchone()
        if row is None:
            raise DomainError("TASK_DRAFT_NOT_FOUND", "任务草稿不存在", status_code=404)
        return self.repo.decode(row, ("config_document",)) or {}

    def patch_draft(self, draft_id: str, payload: dict[str, Any]) -> dict[str, object]:
        """Persist an in-progress workspace without requiring a runnable MatchingConfig.

        STEP1 is intentionally allowed to be incomplete: users can have only a source file,
        half-finished field mappings, or temporarily invalid thresholds while editing. Full
        validation still happens in ``save_rules`` / ``start`` before execution.
        """
        draft = self.get_draft(draft_id)
        allowed = {
            "name",
            "source_file_id",
            "catalog_version_id",
            "template_profile_id",
            "template_profile_version",
            "config_document",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise DomainError(
                "INVALID_REQUEST",
                "任务草稿包含不支持的字段",
                status_code=422,
                details={"fields": sorted(unknown)},
            )

        template_profile_id = payload.get("template_profile_id", draft.get("template_profile_id"))
        template_profile_version = payload.get("template_profile_version", draft.get("template_profile_version"))
        if template_profile_id is None and template_profile_version is None:
            pass
        elif template_profile_id is None or template_profile_version is None:
            raise DomainError("PROFILE_VERSION_NOT_FOUND", "匹配方案来源必须同时包含方案和版本", status_code=422)
        else:
            self._validate_template_source(str(template_profile_id), int(template_profile_version))

        updates: list[str] = []
        values: list[object] = []
        for field in (
            "name",
            "source_file_id",
            "catalog_version_id",
            "template_profile_id",
            "template_profile_version",
        ):
            if field in payload:
                value = payload[field]
                if field == "name":
                    value = str(value or "").strip()
                    if not value:
                        raise DomainError("INVALID_REQUEST", "任务名称不能为空", status_code=422)
                updates.append(f"{field}=?")
                values.append(value)

        if "config_document" in payload:
            document = payload.get("config_document")
            if document is None:
                document = {}
            if not isinstance(document, dict):
                raise DomainError("INVALID_PROFILE", "匹配规则格式不正确", status_code=422)
            updates.append("config_document=?")
            values.append(_canonical(document))

        if not updates:
            return draft
        if any(key in payload for key in ("source_file_id", "catalog_version_id", "config_document")):
            updates.append("current_step=2")
        updates.append("updated_at=?")
        values.append(_now())
        values.append(draft_id)
        with self.repo.connect() as connection:
            connection.execute(
                f"UPDATE task_drafts SET {', '.join(updates)} WHERE draft_id=?",
                tuple(values),
            )
        return self.get_draft(draft_id)

    def save_data(self, draft_id: str, payload: dict[str, Any]) -> dict[str, object]:
        draft = self.get_draft(draft_id)
        template_profile_id = payload.get("template_profile_id")
        template_profile_version = payload.get("template_profile_version")
        if template_profile_id is None:
            template_profile_id = draft.get("template_profile_id")
        if template_profile_version is None:
            template_profile_version = draft.get("template_profile_version")
        with self.repo.connect() as connection:
            connection.execute(
                """UPDATE task_drafts SET source_file_id=?, catalog_version_id=?, template_profile_id=?, template_profile_version=?, current_step=2, updated_at=? WHERE draft_id=?""",
                (
                    payload.get("source_file_id"),
                    payload.get("catalog_version_id"),
                    template_profile_id,
                    template_profile_version,
                    _now(),
                    draft_id,
                ),
            )
        return self.get_draft(draft_id)

    def save_rules(self, draft_id: str, document: dict[str, Any]) -> dict[str, object]:
        draft = self.get_draft(draft_id)
        bound_document = self.dictionaries.bind_references(document)
        MatchingConfig.model_validate(bound_document)
        template_profile_id = draft.get("template_profile_id")
        template_profile_version = draft.get("template_profile_version")
        advanced = bound_document.get("advanced")
        if isinstance(advanced, dict):
            template_source = advanced.get("template_source")
            if isinstance(template_source, dict):
                source_profile_id = template_source.get("profile_id")
                source_version = template_source.get("version_no")
                if source_profile_id and source_version is not None:
                    template_profile_id = str(source_profile_id)
                    template_profile_version = int(source_version)
                    self._validate_template_source(template_profile_id, template_profile_version)
        with self.repo.connect() as connection:
            connection.execute(
                "UPDATE task_drafts SET config_document=?, template_profile_id=?, template_profile_version=?, current_step=2, updated_at=? WHERE draft_id=?",
                (_canonical(bound_document), template_profile_id, template_profile_version, _now(), draft_id),
            )
        return self.get_draft(draft_id)

    def start(self, draft_id: str, actor: str = "system") -> dict[str, object]:
        draft = self.get_draft(draft_id)
        if not draft.get("source_file_id") or not draft.get("catalog_version_id"):
            raise DomainError("TASK_DRAFT_INCOMPLETE", "请先选择客户物料数据和集团码目录", status_code=422)
        bound_document = self.dictionaries.bind_references(dict(draft.get("config_document") or {}))
        config = MatchingConfig.model_validate(bound_document)
        if not config.rules:
            raise DomainError("INVALID_PROFILE", "至少配置一条字段对应关系后才能开始比对", status_code=422)
        snapshot = config.model_dump(mode="json")
        encoded = _canonical(snapshot)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        task_id = uuid.uuid4().hex
        created_at = _now()
        with self.repo.connect() as connection:
            connection.execute(
                """INSERT INTO tasks(
                    task_id,name,source_file_id,catalog_version_id,profile_id,profile_version,
                    config_snapshot,config_sha256,stage,status,progress,processed_rows,total_rows,
                    created_at,started_at,finished_at,error_code,error_message,result_file_id,
                    created_by,started_by
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    task_id,
                    draft["name"],
                    draft["source_file_id"],
                    draft["catalog_version_id"],
                    draft.get("template_profile_id"),
                    draft.get("template_profile_version"),
                    encoded,
                    digest,
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
                    actor or "system",
                    actor or "system",
                ),
            )
            connection.execute(
                "INSERT INTO audit_events VALUES(?,?,?,?,?,?)",
                (
                    uuid.uuid4().hex,
                    "task",
                    task_id,
                    "CONFIG_SNAPSHOT_FROZEN",
                    _canonical({"config_sha256": digest, "created_by": actor or "system", "started_by": actor or "system"}),
                    created_at,
                ),
            )
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> dict[str, object]:
        with self.repo.connect() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise DomainError("TASK_NOT_FOUND", "任务不存在", status_code=404)
        return self.repo.decode(row, ("config_snapshot",)) or {}

    def list_tasks(self) -> list[dict[str, object]]:
        with self.repo.connect() as connection:
            rows = connection.execute("SELECT * FROM tasks ORDER BY created_at DESC").fetchall()
        return [self.repo.decode(row, ("config_snapshot",)) or {} for row in rows]
