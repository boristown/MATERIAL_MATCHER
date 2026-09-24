from __future__ import annotations

import json
from pathlib import Path
import re

from material_matcher.domain.errors import DomainError
from material_matcher.storage.files import FileRepository
from material_matcher.storage.metadata import MetadataRepository


AssetRole = str
_UNAVAILABLE_MESSAGE = "该历史任务的原始文件已无法确认"
_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_MEDIA_TYPES = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    ".csv": "text/csv; charset=utf-8",
}


class TaskInputAssetService:
    """Freeze and resolve the exact source and target files used by a task.

    Composite tasks freeze one source plus one independent target file for every
    child profile/version. No merged or virtual Excel is created.
    """

    def __init__(self, metadata: MetadataRepository, files: FileRepository) -> None:
        self.meta = metadata
        self.files = files

    @staticmethod
    def safe_download_name(value: object, *, max_length: int = 180) -> str:
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

    def _validated_record(self, file_id: object, expected_role: str) -> dict[str, object]:
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
    def _snapshot(
        record: dict[str, object],
        *,
        catalog_version_id: str | None = None,
        profile_id: str | None = None,
        profile_version: int | None = None,
    ) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "file_id": str(record["file_id"]),
            "original_name": str(record.get("original_name") or ""),
            "role": str(record.get("role") or ""),
            "size_bytes": int(record.get("size_bytes") or 0),
            "uploaded_at": str(record.get("created_at") or ""),
        }
        if catalog_version_id:
            snapshot["catalog_version_id"] = catalog_version_id
        if profile_id:
            snapshot["profile_id"] = profile_id
        if profile_version is not None:
            snapshot["profile_version"] = int(profile_version)
        return snapshot

    def _published_composite_children(
        self,
        profile_id: object | None,
        version_no: object | None,
    ) -> list[dict[str, object]]:
        if not profile_id or version_no is None:
            return []
        with self.meta.connect() as connection:
            row = connection.execute(
                "SELECT document,status FROM profile_versions WHERE profile_id=? AND version_no=?",
                (str(profile_id), int(version_no)),
            ).fetchone()
        if row is None or str(row["status"] or "") != "PUBLISHED":
            raise DomainError(
                "PROFILE_VERSION_NOT_FOUND",
                "任务引用的匹配方案发布版本不存在",
                status_code=422,
            )
        try:
            document = json.loads(str(row["document"] or "{}"))
        except (TypeError, ValueError) as exc:
            raise DomainError("INVALID_PROFILE", "匹配方案版本内容无法解析", status_code=422) from exc
        advanced = document.get("advanced") if isinstance(document, dict) else {}
        if not isinstance(advanced, dict) or str(advanced.get("profile_kind") or "single").lower() != "composite":
            return []
        raw_children = advanced.get("composite_children")
        if not isinstance(raw_children, list) or len(raw_children) < 2:
            raise DomainError("INVALID_PROFILE", "组合匹配方案缺少子方案版本", status_code=422)
        children: list[dict[str, object]] = []
        seen: set[str] = set()
        for raw in raw_children:
            if not isinstance(raw, dict):
                raise DomainError("INVALID_PROFILE", "组合匹配方案的子方案引用格式不正确", status_code=422)
            child_id = str(raw.get("profile_id") or "").strip()
            try:
                child_version = int(raw.get("version_no"))
            except (TypeError, ValueError):
                child_version = 0
            if not child_id or child_version <= 0 or child_id in seen:
                raise DomainError("INVALID_PROFILE", "组合匹配方案的子方案引用不完整或重复", status_code=422)
            with self.meta.connect() as connection:
                child = connection.execute(
                    "SELECT status FROM profile_versions WHERE profile_id=? AND version_no=?",
                    (child_id, child_version),
                ).fetchone()
            if child is None or str(child["status"] or "") != "PUBLISHED":
                raise DomainError(
                    "PROFILE_VERSION_NOT_FOUND",
                    "组合任务引用的子方案版本不存在",
                    status_code=422,
                    details={"profile_id": child_id, "version_no": child_version},
                )
            seen.add(child_id)
            children.append({"profile_id": child_id, "version_no": child_version})
        return children

    def validate_for_freeze(self, draft_id: str) -> None:
        """Cheap, synchronous pre-flight for /start: existence + role only.

        Keeps the historical HTTP contract (404/422 raised from the request)
        while the heavy full-file hashing runs in the background freeze.
        """
        with self.meta.connect() as connection:
            draft = connection.execute(
                "SELECT source_file_id FROM task_drafts WHERE draft_id=?", (draft_id,)
            ).fetchone()
            if draft is None:
                raise DomainError("TASK_DRAFT_NOT_FOUND", "任务草稿不存在", status_code=404)
            if not draft["source_file_id"]:
                raise DomainError("TASK_DRAFT_INCOMPLETE", "请先选择待匹配源数据", status_code=422)
            target_rows = connection.execute(
                "SELECT catalog_version_id FROM task_draft_targets WHERE draft_id=?", (draft_id,)
            ).fetchall()
            records: list[tuple[str, str]] = [(str(draft["source_file_id"]), "source")]
            for row in target_rows:
                if not row["catalog_version_id"]:
                    continue
                catalog = connection.execute(
                    "SELECT source_file_id,status FROM catalog_versions WHERE version_id=?",
                    (str(row["catalog_version_id"]),),
                ).fetchone()
                if catalog is None:
                    raise DomainError("CATALOG_VERSION_NOT_FOUND", "组合任务引用的集团码目录版本不存在", status_code=422)
                if str(catalog["status"] or "") != "READY":
                    raise DomainError("CATALOG_NOT_READY", "组合任务引用的集团码目录版本不可用于正式计算", status_code=409)
                records.append((str(catalog["source_file_id"]), "target"))
        for file_id, role in records:
            self._validated_record(file_id, role)

    def freeze_draft(self, draft_id: str) -> dict[str, dict[str, object]]:
        with self.meta.connect() as connection:
            draft = connection.execute(
                """SELECT source_file_id,catalog_version_id,template_profile_id,template_profile_version
                   FROM task_drafts WHERE draft_id=?""",
                (draft_id,),
            ).fetchone()
            target_rows = connection.execute(
                """SELECT profile_id,profile_version,catalog_version_id
                   FROM task_draft_targets WHERE draft_id=?
                   ORDER BY binding_order,profile_id""",
                (draft_id,),
            ).fetchall()
        if draft is None:
            raise DomainError("TASK_DRAFT_NOT_FOUND", "任务草稿不存在", status_code=404)
        if not draft["source_file_id"]:
            raise DomainError("TASK_DRAFT_INCOMPLETE", "请先选择待匹配源数据", status_code=422)

        source = self._validated_record(draft["source_file_id"], "source")
        frozen: dict[str, dict[str, object]] = {"source": self._snapshot(source)}
        children = self._published_composite_children(
            draft["template_profile_id"],
            draft["template_profile_version"],
        )
        if children:
            expected = {(str(item["profile_id"]), int(item["version_no"])) for item in children}
            actual = {
                (str(row["profile_id"]), int(row["profile_version"]))
                for row in target_rows
                if row["catalog_version_id"]
            }
            if actual != expected:
                raise DomainError(
                    "TASK_DRAFT_INCOMPLETE",
                    "请为组合方案的每个子方案选择对应的集团码目标文件",
                    status_code=422,
                    details={"required_targets": len(expected), "ready_targets": len(actual)},
                )
            for row in target_rows:
                profile_id = str(row["profile_id"])
                profile_version = int(row["profile_version"])
                catalog_version_id = str(row["catalog_version_id"])
                with self.meta.connect() as connection:
                    catalog = connection.execute(
                        "SELECT source_file_id,status FROM catalog_versions WHERE version_id=?",
                        (catalog_version_id,),
                    ).fetchone()
                if catalog is None:
                    raise DomainError(
                        "CATALOG_VERSION_NOT_FOUND",
                        "组合任务引用的集团码目录版本不存在",
                        status_code=422,
                        details={"profile_id": profile_id, "catalog_version_id": catalog_version_id},
                    )
                if str(catalog["status"] or "") != "READY":
                    raise DomainError(
                        "CATALOG_NOT_READY",
                        "组合任务引用的集团码目录版本不可用于正式计算",
                        status_code=409,
                        details={"profile_id": profile_id, "catalog_version_id": catalog_version_id},
                    )
                target = self._validated_record(catalog["source_file_id"], "target")
                frozen[f"target.{profile_id}"] = self._snapshot(
                    target,
                    catalog_version_id=catalog_version_id,
                    profile_id=profile_id,
                    profile_version=profile_version,
                )
            return frozen

        catalog_version_id = draft["catalog_version_id"]
        if not catalog_version_id:
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
        target = self._validated_record(catalog["source_file_id"], "target")
        frozen["target"] = self._snapshot(target, catalog_version_id=str(catalog_version_id))
        return frozen

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

    def _composite_frozen_rows(self, task_id: str) -> list[dict[str, object]]:
        with self.meta.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM task_input_assets
                   WHERE task_id=? AND asset_role LIKE 'target.%'
                   ORDER BY rowid""",
                (task_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _legacy_file_id(self, task: dict[str, object], role: AssetRole) -> str | None:
        if role == "source":
            value = task.get("source_file_id")
            return str(value) if value else None
        if role != "target":
            return None
        if self._composite_frozen_rows(str(task["task_id"])):
            return None
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

    @staticmethod
    def _expected_upload_role(asset_role: str) -> str:
        return "target" if asset_role == "target" or asset_role.startswith("target.") else "source"

    def _resolve(self, task_id: str, role: AssetRole) -> tuple[dict[str, object] | None, dict[str, object] | None]:
        task = self._task_row(task_id)
        frozen = self._frozen_row(task_id, role)
        file_id = (
            str(frozen["file_id"])
            if frozen is not None and frozen.get("file_id")
            else self._legacy_file_id(task, role)
        )
        if not file_id:
            return frozen, None
        try:
            record = self.files.get(file_id)
        except DomainError:
            return frozen, None
        if str(record.get("role") or "") != self._expected_upload_role(role):
            return frozen, None
        return frozen, record

    def _describe_asset(
        self,
        task_id: str,
        asset_role: str,
        label: str,
        *,
        target_download_url: str | None = None,
    ) -> dict[str, object]:
        frozen, record = self._resolve(task_id, asset_role)
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
        item: dict[str, object] = {
            "kind": "source" if asset_role == "source" else "target",
            "label": label,
            "original_name": original_name or None,
            "uploaded_at": created_at or None,
            "size_bytes": size_bytes,
            "available": available,
            "download_url": (
                target_download_url
                if available and target_download_url
                else f"/api/tasks/{task_id}/input-files/{asset_role}" if available else None
            ),
            "message": None if available else _UNAVAILABLE_MESSAGE,
        }
        if frozen:
            if frozen.get("catalog_version_id"):
                item["catalog_version_id"] = str(frozen["catalog_version_id"])
            if frozen.get("profile_id"):
                item["profile_id"] = str(frozen["profile_id"])
            if frozen.get("profile_version") is not None:
                item["profile_version"] = int(frozen["profile_version"])
        return item

    def describe(self, task_id: str) -> dict[str, object]:
        self._task_row(task_id)
        source = self._describe_asset(task_id, "source", "待匹配源数据")
        composite_rows = self._composite_frozen_rows(task_id)
        if not composite_rows:
            return {
                "composite": False,
                "source": source,
                "target": self._describe_asset(task_id, "target", "集团码标准数据"),
                "targets": [],
            }

        targets: list[dict[str, object]] = []
        for index, row in enumerate(composite_rows, start=1):
            profile_id = str(row.get("profile_id") or str(row["asset_role"]).split(".", 1)[-1])
            profile_version = row.get("profile_version")
            with self.meta.connect() as connection:
                profile = connection.execute(
                    "SELECT name FROM profiles WHERE profile_id=?",
                    (profile_id,),
                ).fetchone()
            profile_name = str(profile["name"] or "").strip() if profile is not None else ""
            label = profile_name or f"子方案 {index}"
            target = self._describe_asset(
                task_id,
                str(row["asset_role"]),
                label,
                target_download_url=f"/api/tasks/{task_id}/input-files/targets/{profile_id}",
            )
            target["profile_id"] = profile_id
            target["profile_name"] = profile_name or None
            if profile_version is not None:
                target["profile_version"] = int(profile_version)
            targets.append(target)
        return {
            "composite": True,
            "source": source,
            "target": None,
            "targets": targets,
        }

    def _download_resolved(self, task_id: str, role: AssetRole) -> dict[str, object]:
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

    def download(self, task_id: str, role: AssetRole) -> dict[str, object]:
        if role not in {"source", "target"}:
            raise DomainError("INVALID_FILE_ROLE", "原始文件用途不正确", status_code=422)
        return self._download_resolved(task_id, role)

    def download_target(self, task_id: str, profile_id: str) -> dict[str, object]:
        profile_id = str(profile_id or "").strip()
        if not profile_id or "." in profile_id or "/" in profile_id or "\\" in profile_id:
            raise DomainError("INVALID_FILE_ROLE", "子方案标识不正确", status_code=422)
        role = f"target.{profile_id}"
        frozen = self._frozen_row(task_id, role)
        if frozen is None:
            raise DomainError("ORIGINAL_FILE_UNAVAILABLE", _UNAVAILABLE_MESSAGE, status_code=404)
        return self._download_resolved(task_id, role)
