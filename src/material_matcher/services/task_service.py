from __future__ import annotations

from datetime import datetime
import hashlib
import json
import re
from typing import Any
import uuid

from material_matcher.domain.errors import DomainError
from material_matcher.domain.models import MatchingConfig
from material_matcher.services.dictionary_service import DictionaryService
from material_matcher.storage.metadata import MetadataRepository


UNNAMED_SCHEME = "未命名方案"
SCHEME_SNAPSHOT_KEY = "scheme_display_name"


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def _parse_timestamp(value: object) -> datetime | None:
    if value in {None, ""}:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _duration_ms(started_at: object, completed_at: object) -> int | None:
    started = _parse_timestamp(started_at)
    completed = _parse_timestamp(completed_at)
    if started is None or completed is None:
        return None
    if (started.tzinfo is None) != (completed.tzinfo is None):
        return None
    milliseconds = int(round((completed - started).total_seconds() * 1000))
    return milliseconds if milliseconds >= 0 else None


def format_duration_ms(value: object) -> str:
    if value is None:
        return "暂无准确记录"
    try:
        milliseconds = float(value)
    except (TypeError, ValueError):
        return "暂无准确记录"
    if milliseconds < 0:
        return "暂无准确记录"
    total_seconds = int(round(milliseconds / 1000.0))
    if total_seconds < 60:
        return f"{total_seconds} 秒"
    minutes, seconds = divmod(total_seconds, 60)
    if minutes < 60:
        return f"{minutes} 分 {seconds} 秒"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} 小时 {minutes} 分 {seconds} 秒"


def task_time_fields(
    repo: MetadataRepository,
    task: dict[str, object],
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    """Return the single business timing contract consumed by every surface.

    started_at is the user click-to-start time. compute_duration_ms is only the
    recorded automatic matching window; human wait/review/export/re-decide time
    is intentionally impossible to enter this calculation.
    """
    business_started_at = task.get("started_at") or task.get("created_at")
    compute_started_at = task.get("compute_started_at")
    compute_completed_at = task.get("compute_completed_at")
    timing_source: str | None = None

    if ("compute_started_at" not in task or "compute_completed_at" not in task) and task.get("task_id"):
        with repo.connect() as connection:
            row = connection.execute(
                "SELECT compute_started_at,compute_completed_at FROM task_compute_lifecycle WHERE task_id=?",
                (str(task["task_id"]),),
            ).fetchone()
        if row is not None:
            compute_started_at = row["compute_started_at"]
            compute_completed_at = row["compute_completed_at"]

    if compute_started_at and compute_completed_at:
        timing_source = "recorded"
    elif (
        not compute_started_at
        and not compute_completed_at
        and str(task.get("status") or "") == "COMPLETED"
        and task.get("started_at")
        and task.get("finished_at")
        and task.get("created_at")
        and str(task.get("started_at")) != str(task.get("created_at"))
    ):
        # Compatibility for a legacy row inserted after the migration has
        # already run. Pre-migration code used started_at/finished_at exactly as
        # the automatic compute window. Never use updated_at or result time.
        compute_started_at = task.get("started_at")
        compute_completed_at = task.get("finished_at")
        timing_source = "legacy_started_finished"

    compute_duration_ms = _duration_ms(compute_started_at, compute_completed_at)
    compute_elapsed_ms = compute_duration_ms
    if compute_elapsed_ms is None and compute_started_at and not compute_completed_at:
        started = _parse_timestamp(compute_started_at)
        current = now or datetime.now().astimezone()
        if started is not None:
            if started.tzinfo is None and current.tzinfo is not None:
                current = current.replace(tzinfo=None)
            elapsed = int(round((current - started).total_seconds() * 1000))
            compute_elapsed_ms = elapsed if elapsed >= 0 else None

    return {
        "started_at": business_started_at,
        "compute_started_at": compute_started_at,
        "compute_completed_at": compute_completed_at,
        "compute_duration_ms": compute_duration_ms,
        "compute_elapsed_ms": compute_elapsed_ms,
        "compute_timing_source": timing_source,
    }


def resolve_task_scheme_name(repo: MetadataRepository, task: dict[str, Any]) -> str:
    """Single business-name resolver for every screen, export and file name.

    Order: frozen start-time snapshot -> linked profile -> 未命名方案.
    It must never fall back to tasks.name: that column is an internal
    compatibility field (run-xxxxxxxx, or legacy SMOKE/test values).
    """
    snapshot = task.get("config_snapshot")
    if isinstance(snapshot, str):
        try:
            snapshot = json.loads(snapshot)
        except (TypeError, ValueError):
            snapshot = None
    frozen = TaskService.snapshot_scheme_name(snapshot)
    if frozen:
        return frozen
    profile_id = task.get("profile_id")
    if profile_id:
        with repo.connect() as connection:
            row = connection.execute("SELECT name FROM profiles WHERE profile_id=?", (str(profile_id),)).fetchone()
        if row is not None:
            name = str(row["name"] or "").strip()
            if name:
                return name
    return UNNAMED_SCHEME


_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def safe_business_filename(scheme_name: object, max_length: int = 60) -> str:
    """Turn a scheme name into a safe file-name fragment for business users."""
    text = _UNSAFE_FILENAME.sub("", str(scheme_name or "")).strip().strip(".")
    text = re.sub(r"\s+", " ", text)
    if not text:
        return UNNAMED_SCHEME
    return text[:max_length].rstrip(" .")


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

    def _profile_name(self, profile_id: object | None) -> str | None:
        if not profile_id:
            return None
        with self.repo.connect() as connection:
            row = connection.execute(
                "SELECT name FROM profiles WHERE profile_id=?",
                (str(profile_id),),
            ).fetchone()
        if row is None:
            return None
        name = str(row["name"] or "").strip()
        return name or None

    @staticmethod
    @staticmethod
    def snapshot_scheme_name(snapshot: object) -> str | None:
        return TaskService._snapshot_scheme_name(snapshot)

    @staticmethod
    def _snapshot_scheme_name(snapshot: object) -> str | None:
        if not isinstance(snapshot, dict):
            return None
        advanced = snapshot.get("advanced")
        if not isinstance(advanced, dict):
            return None
        for key in (SCHEME_SNAPSHOT_KEY, "scheme_name", "plan_name", "profile_name"):
            value = str(advanced.get(key) or "").strip()
            if value:
                return value
        return None

    def _freeze_scheme_name(self, snapshot: dict[str, Any], draft: dict[str, object]) -> str:
        existing = self._snapshot_scheme_name(snapshot)
        if existing:
            return existing
        scheme_name = self._profile_name(draft.get("template_profile_id")) or UNNAMED_SCHEME
        advanced = dict(snapshot.get("advanced") or {})
        advanced[SCHEME_SNAPSHOT_KEY] = scheme_name
        snapshot["advanced"] = advanced
        return scheme_name

    def _with_scheme_name(self, task: dict[str, object]) -> dict[str, object]:
        # New tasks always read the immutable start-time snapshot. For legacy tasks
        # created before this field existed, the linked profile is the best available
        # business source. Never fall back to task.name because it may be SMOKE-/test-/run-*.
        task["scheme_name"] = resolve_task_scheme_name(self.repo, task)
        return task

    def _with_time_fields(self, task: dict[str, object]) -> dict[str, object]:
        task.update(task_time_fields(self.repo, task))
        return task

    def create_draft(
        self,
        name: str | None = None,
        *,
        template_profile_id: str | None = None,
        template_profile_version: int | None = None,
        config_document: dict[str, Any] | None = None,
    ) -> dict[str, object]:
        draft_id = uuid.uuid4().hex
        created_at = _now()
        # "任务名称" is no longer a business concept. The legacy column keeps only a
        # system-generated internal id (run-xxxxxxxx); user input is never consumed.
        internal_name = f"run-{draft_id[:8]}"
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
                    internal_name,
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
                    # Legacy clients may still send name; it is accepted for API
                    # compatibility and then ignored — drafts have no business name.
                    continue
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
        scheme_name = self._freeze_scheme_name(snapshot, draft)
        encoded = _canonical(snapshot)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        task_id = uuid.uuid4().hex
        created_at = _now()
        actor_name = actor or "system"
        internal_name = f"run-{task_id[:8]}"
        with self.repo.connect() as connection:
            connection.execute(
                "INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    task_id,
                    internal_name,
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
                    created_at,
                    None,
                    None,
                    None,
                    None,
                ),
            )
            connection.execute(
                "INSERT INTO task_actors(task_id,created_by,started_by) VALUES(?,?,?)",
                (task_id, actor_name, actor_name),
            )
            connection.execute(
                "INSERT INTO audit_events VALUES(?,?,?,?,?,?)",
                (
                    uuid.uuid4().hex,
                    "task",
                    task_id,
                    "CONFIG_SNAPSHOT_FROZEN",
                    _canonical({
                        "config_sha256": digest,
                        "scheme_display_name": scheme_name,
                        "created_by": actor_name,
                        "started_by": actor_name,
                    }),
                    created_at,
                ),
            )
        return self.get_task(task_id)

    @staticmethod
    def _with_actor_fields(task: dict[str, object], actor_row: Any | None) -> dict[str, object]:
        task["created_by"] = str(actor_row["created_by"]) if actor_row is not None and actor_row["created_by"] is not None else None
        task["started_by"] = str(actor_row["started_by"]) if actor_row is not None and actor_row["started_by"] is not None else None
        return task

    def get_task(self, task_id: str) -> dict[str, object]:
        with self.repo.connect() as connection:
            row = connection.execute(
                """SELECT t.*,l.compute_started_at,l.compute_completed_at
                   FROM tasks t
                   LEFT JOIN task_compute_lifecycle l ON l.task_id=t.task_id
                   WHERE t.task_id=?""",
                (task_id,),
            ).fetchone()
            actor_row = connection.execute("SELECT created_by,started_by FROM task_actors WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise DomainError("TASK_NOT_FOUND", "任务不存在", status_code=404)
        task = self.repo.decode(row, ("config_snapshot",)) or {}
        with self.repo.connect() as connection:
            run_count = connection.execute(
                """SELECT CASE WHEN ? IS NOT NULL THEN
                          (SELECT COUNT(*) FROM tasks t2 WHERE t2.profile_id=?
                            AND (t2.created_at<? OR (t2.created_at=? AND t2.task_id<=?)))
                        ELSE
                          (SELECT COUNT(*) FROM tasks t2 WHERE t2.profile_id IS NULL AND t2.source_file_id=?
                            AND t2.catalog_version_id=? AND t2.config_sha256=?
                            AND (t2.created_at<? OR (t2.created_at=? AND t2.task_id<=?)))
                        END""",
                (
                    task.get("profile_id"), task.get("profile_id"),
                    task.get("created_at"), task.get("created_at"), task_id,
                    task.get("source_file_id"), task.get("catalog_version_id"), task.get("config_sha256"),
                    task.get("created_at"), task.get("created_at"), task_id,
                ),
            ).fetchone()[0]
        task["run_number"] = int(run_count or 1)
        return self._with_scheme_name(self._with_actor_fields(self._with_time_fields(task), actor_row))

    def list_tasks(self) -> list[dict[str, object]]:
        with self.repo.connect() as connection:
            rows = connection.execute(
                """SELECT t.*, a.created_by AS actor_created_by, a.started_by AS actor_started_by,
                          l.compute_started_at,l.compute_completed_at,
(CASE WHEN t.profile_id IS NOT NULL THEN
                          (SELECT COUNT(*) FROM tasks t2
                            WHERE t2.profile_id=t.profile_id
                              AND (t2.created_at<t.created_at OR (t2.created_at=t.created_at AND t2.task_id<=t.task_id)))
                        ELSE
                          (SELECT COUNT(*) FROM tasks t2
                            WHERE t2.profile_id IS NULL AND t2.source_file_id=t.source_file_id
                              AND t2.catalog_version_id=t.catalog_version_id AND t2.config_sha256=t.config_sha256
                              AND (t2.created_at<t.created_at OR (t2.created_at=t.created_at AND t2.task_id<=t.task_id)))
                        END) AS run_number
                   FROM tasks t
                   LEFT JOIN task_actors a ON a.task_id=t.task_id
                   LEFT JOIN task_compute_lifecycle l ON l.task_id=t.task_id
                   ORDER BY t.created_at DESC"""
            ).fetchall()
        result: list[dict[str, object]] = []
        for row in rows:
            item = self.repo.decode(row, ("config_snapshot",)) or {}
            item["created_by"] = item.pop("actor_created_by", None)
            item["started_by"] = item.pop("actor_started_by", None)
            item["run_number"] = int(item.get("run_number") or 1)
            result.append(self._with_scheme_name(self._with_time_fields(item)))
        return result

    def review_history(self) -> list[dict[str, object]]:
        """STEP3 history summary: one aggregate query, business scheme names, stable ordinals.

        Returns every completed calculation that can be opened in the review workbench,
        newest first. Per-task counts come from a single GROUP BY over the covering
        match_items index (no per-task summary round-trips); "第 N 次计算" ordinals are
        derived per scheme from the immutable start time so the numbering never jumps
        between refreshes. Tasks whose business scheme cannot be recovered keep
        sequence=None and the UI labels them "历史计算" instead of a fake ordinal.
        """
        with self.repo.connect() as connection:
            rows = connection.execute(
                """SELECT t.task_id,t.config_snapshot,t.profile_id,t.stage,t.status,t.total_rows,
                          t.created_at,t.started_at,t.finished_at,t.result_file_id,
                          l.compute_started_at,l.compute_completed_at,
                          COALESCE(SUM(CASE WHEN m.current_status='MATCHED' THEN 1 ELSE 0 END),0) AS matched_count,
                          COALESCE(SUM(CASE WHEN m.current_status='REVIEW' THEN 1 ELSE 0 END),0) AS review_count,
                          COALESCE(SUM(CASE WHEN m.current_status='CONFIRMED' THEN 1 ELSE 0 END),0) AS confirmed_count,
                          COALESCE(SUM(CASE WHEN m.current_status='UNMATCHED' THEN 1 ELSE 0 END),0) AS unmatched_count
                   FROM tasks t
                   LEFT JOIN task_compute_lifecycle l ON l.task_id=t.task_id
                   LEFT JOIN match_items m ON m.task_id=t.task_id
                   WHERE t.status='COMPLETED' AND t.stage IN ('REVIEW','RESULT')
                   GROUP BY t.task_id
                   ORDER BY COALESCE(t.started_at,t.created_at) DESC,t.task_id DESC"""
            ).fetchall()
        items: list[dict[str, object]] = []
        missing_profile_ids: set[str] = set()
        for row in rows:
            decoded = self.repo.decode(row, ("config_snapshot",)) or {}
            snapshot = decoded.get("config_snapshot")
            scheme_name = self._snapshot_scheme_name(snapshot)
            profile_id = str(row["profile_id"]) if row["profile_id"] else None
            if scheme_name is None and profile_id:
                missing_profile_ids.add(profile_id)
            items.append(
                {
                    "task_id": str(row["task_id"]),
                    "scheme_name": scheme_name or "",
                    "profile_id": profile_id,
                    "stage": str(row["stage"]),
                    "status": str(row["status"]),
                    "result_file_id": str(row["result_file_id"]) if row["result_file_id"] else None,
                    "started_at": str(row["started_at"]) if row["started_at"] else None,
                    "finished_at": str(row["finished_at"]) if row["finished_at"] else None,
                    "compute_started_at": str(row["compute_started_at"]) if row["compute_started_at"] else None,
                    "compute_completed_at": str(row["compute_completed_at"]) if row["compute_completed_at"] else None,
                    "created_at": str(row["created_at"]),
                    "total": int(row["total_rows"] or 0),
                    "matched": int(row["matched_count"] or 0),
                    "review": int(row["review_count"] or 0),
                    "confirmed": int(row["confirmed_count"] or 0),
                    "unmatched": int(row["unmatched_count"] or 0),
                }
            )
            items[-1].update(task_time_fields(self.repo, items[-1]))
        profile_names: dict[str, str] = {}
        if missing_profile_ids:
            with self.repo.connect() as connection:
                placeholders = ",".join("?" * len(missing_profile_ids))
                for profile_row in connection.execute(
                    f"SELECT profile_id,name FROM profiles WHERE profile_id IN ({placeholders})",
                    tuple(sorted(missing_profile_ids)),
                ).fetchall():
                    name = str(profile_row["name"] or "").strip()
                    if name:
                        profile_names[str(profile_row["profile_id"])] = name
        for item in items:
            scheme_name = str(item["scheme_name"])
            if not scheme_name:
                profile_id = item["profile_id"]
                scheme_name = profile_names.get(str(profile_id)) if profile_id else None
                if not scheme_name:
                    scheme_name = UNNAMED_SCHEME
            item["scheme_name"] = scheme_name
            item.pop("profile_id", None)
        groups: dict[str, list[dict[str, object]]] = {}
        for item in sorted(items, key=lambda entry: (str(entry["started_at"] or entry["created_at"]), str(entry["task_id"]))):
            if str(item["scheme_name"]) != UNNAMED_SCHEME:
                groups.setdefault(str(item["scheme_name"]), []).append(item)
        for scheme_group in groups.values():
            for ordinal, item in enumerate(scheme_group, start=1):
                item["sequence"] = ordinal
        for item in items:
            item.setdefault("sequence", None)
            item["sequence_total"] = len(groups[str(item["scheme_name"])]) if str(item["scheme_name"]) in groups else None
            total = int(item["total"] or 0)
            if total <= 0:
                item["total"] = int(item["matched"]) + int(item["review"]) + int(item["confirmed"]) + int(item["unmatched"])
        return items
