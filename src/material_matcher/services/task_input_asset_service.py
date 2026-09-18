from __future__ import annotations

from pathlib import Path
import re
from typing import Literal

from material_matcher.domain.errors import DomainError
from material_matcher.storage.files import FileRepository
from material_matcher.storage.metadata import MetadataRepository


AssetRole = Literal["source", "target"]
_UNAVAILABLE_MESSAGE = "该历史任务的原始文件已无法确认"
_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_MEDIA_TYPES = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    ".csv": "text/csv; charset=utf-8",
}


class TaskInputAssetService:
    """Freeze and resolve the exact uploaded source/target files used by one task.

    The original file bytes remain in FileRepository.  This service only freezes
    immutable references, so task traceability does not duplicate large uploads.
    """

    def __init__(self, metadata: MetadataRepository, files: FileRepository) -> None:
        self.meta = metadata
        self.files = files

    @staticmethod
    def safe_download_name(value: object, *, max_length: int = 180) -> str:
        # Browsers must never receive a client-controlled path in Content-Disposition.
        # Keep Unicode (including Chinese), but drop path separators/control characters.
        basename = str(value or "原始文件").replace("\\", "/").split("/")[-1]
        cleaned = _UNSAFE_FILENAME.sub("", basename).strip().strip(".")
        cleaned = re.sub(r"\s+", " ", cleaned)
        if not cleaned:
            cleaned = "原始文件"
        suffix = Path(cleaned).suffix
        stem = cleaned[: -len(suffix)] if suffix else cleaned
        room = max(1, max_length - len(suffix))
        return f"{stem[:room].rstrip(' .')}{suffix}" if suffix else stem[:max_length].rstrip(" .")

    def _stored_path(self, record: dict[str, object]) -> Path:
        uploads_root = (self.files.root / "uploads").resolve()
        stored_path = Path(str(record.get("stored_path") or "")).resolve()
        try:
            stored_path.relative_to(uploads_root)
        except ValueError as exc:
            raise DomainError(
                "ORIGINAL_FILE_UNAVAILABLE",
                _UNAVAILABLE_MESSAGE,
                status_code=404,
            ) from exc
        if not stored_path.is_file():
            raise DomainError(
                "ORIGINAL_FILE_UNAVAILABLE",
                _UNAVAILABLE_MESSAGE,
                status_code=404,
            )
        return stored_path

    def _validated_record(self, file_id: object, expected_role: AssetRole) -> dict[str, object]:
        try:
            record = self.files.get(str(file_id))
        except DomainError as exc:
            raise DomainError(
                "ORIGINAL_FILE_UNAVAILABLE",
                _UNAVAILABLE_MESSAGE,
                status_code=404,
            ) from exc
        if str(record.get("role") or "") != expected_role:
            raise DomainError(
                "INVALID_FILE_ROLE",
                "任务引用的原始文件用途不正确，无法启动正式计算",
                status_code=422,
            )
        self._stored_path(record)
        return record

    @staticmethod
    def _snapshot(record: dict[str, object], *, catalog_version_id: str | None = None) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "file_id": str(record["file_id"]),
            "original_name": str(record.get("original_name") or ""),
            "role": str(record.get("role") or ""),
            "size_bytes": int(record.get("size_bytes") or 0),
            "uploaded_at": str(record.get("created_at") or ""),
        }
        if catalog_version_id:
            snapshot["catalog_version_id"] = catalog_version_id
        return snapshot

    def freeze_draft(self, draft_id: str) -> dict[str, dict[str, object]]:
        with self.meta.connect() as connection:
            draft = connection.execute(
                "SELECT source_file_id,catalog_version_id FROM task_drafts WHERE draft_id=?",
                (draft_id,),
            ).fetchone()
        if draft is None:
            raise DomainError("TASK_DRAFT_NOT_FOUND", "任务草稿不存在", status_code=404)
        source_file_id = draft["source_file_id"]
        catalog_version_id = draft["catalog_version_id"]
        if not source_file_id or not catalog_version_id:
            raise DomainError(
                "TASK_DRAFT_INCOMPLETE",
                "请先选择待匹配源数据和集团码标准数据",
                status_code=422,
            )

        with self.meta.connect() as connection:
            catalog = connection.execute(
                "SELECT source_file_id,status FROM catalog_versions WHERE version_id=?",
                (str(catalog_version_id),),
            ).fetchone()
        if catalog is None:
            raise DomainError("CATALOG_VERSION_NOT_FOUND", "集团码目录版本不存在", status_code=422)
        if str(catalog["status"] or "") != "READY":
            raise DomainError("CATALOG_NOT_READY", "集团码目录版本不可用于正式计算", status_code=409)

        source = self._validated_record(source_file_id, "source")
        target = self._validated_record(catalog["source_file_id"], "target")
        return {
            "source": self._snapshot(source),
            "target": self._snapshot(target, catalog_version_id=str(catalog_version_id)),
        }

    def _task_row(self, task_id: str) -> dict[str, object]:
        with self.meta.connect() as connection:
            row = connection.execute(
                "SELECT task_id,source_file_id,catalog_version_id,config_snapshot FROM tasks WHERE task_id=?",
                (task_id,),
            ).fetchone()
        if row is None:
            raise DomainError("TASK_NOT_FOUND", "任务不存在", status_code=404)
        return dict(row)

    def _frozen_row(self, task_id: str, role: AssetRole) -> dict[str, object] | None:
        with self.meta.connect() as connection:
            row = connection.execute(
                "SELECT * FROM task_input_assets WHERE task_id=? AND asset_role=?",
                (task_id, role),
            ).fetchone()
        return dict(row) if row is not None else None

    def _legacy_file_id(self, task: dict[str, object], role: AssetRole) -> str | None:
        if role == "source":
            value = task.get("source_file_id")
            return str(value) if value else None
        catalog_version_id = task.get("catalog_version_id")
        if not catalog_version_id:
            return None
        with self.meta.connect() as connection:
            row = connection.execute(
                "SELECT source_file_id FROM catalog_versions WHERE version_id=?",
                (str(catalog_version_id),),
            ).fetchone()
        if row is None or not row["source_file_id"]:
            return None
        return str(row["source_file_id"])

    def _resolve(self, task_id: str, role: AssetRole) -> tuple[dict[str, object] | None, dict[str, object] | None]:
        task = self._task_row(task_id)
        frozen = self._frozen_row(task_id, role)
        file_id = str(frozen["file_id"]) if frozen is not None and frozen.get("file_id") else self._legacy_file_id(task, role)
        if not file_id:
            return frozen, None
        try:
            record = self.files.get(file_id)
        except DomainError:
            return frozen, None
        if str(record.get("role") or "") != role:
            return frozen, None
        return frozen, record

    def describe(self, task_id: str) -> dict[str, object]:
        result: dict[str, object] = {}
        for role, label in (("source", "待匹配源数据"), ("target", "集团码标准数据")):
            frozen, record = self._resolve(task_id, role)
            original_name = str(
                (frozen or {}).get("original_name")
                or (record or {}).get("original_name")
                or ""
            )
            created_at = str(
                (frozen or {}).get("uploaded_at")
                or (record or {}).get("created_at")
                or ""
            )
            size_bytes = int((record or {}).get("size_bytes") or 0) if record else None
            available = False
            if record is not None:
                try:
                    self._stored_path(record)
                    available = True
                except DomainError:
                    available = False
            result[role] = {
                "kind": role,
                "label": label,
                "original_name": original_name or None,
                "uploaded_at": created_at or None,
                "size_bytes": size_bytes,
                "available": available,
                "download_url": f"/api/tasks/{task_id}/input-files/{role}" if available else None,
                "message": None if available else _UNAVAILABLE_MESSAGE,
            }
        return result

    def download(self, task_id: str, role: AssetRole) -> dict[str, object]:
        _, record = self._resolve(task_id, role)
        if record is None:
            raise DomainError("ORIGINAL_FILE_UNAVAILABLE", _UNAVAILABLE_MESSAGE, status_code=404)
        path = self._stored_path(record)
        suffix = path.suffix.lower()
        return {
            "path": path,
            "filename": self.safe_download_name(record.get("original_name")),
            "media_type": _MEDIA_TYPES.get(suffix, "application/octet-stream"),
        }
