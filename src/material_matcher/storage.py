from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml


_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_name(value: str, fallback: str = "item") -> str:
    cleaned = _SAFE_NAME.sub("_", value.strip()).strip("._-")
    return cleaned[:120] or fallback


@dataclass
class UploadRecord:
    file_id: str
    role: str
    original_name: str
    stored_name: str
    size: int
    created_at: float
    path: str


class RuntimeStorage:
    def __init__(self, data_dir: Path, config_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.config_dir = Path(config_dir)
        self.uploads_dir = self.data_dir / "tmp" / "uploads"
        self.tasks_dir = self.data_dir / "tasks"
        self.results_dir = self.data_dir / "results"
        self.catalogs_dir = self.data_dir / "catalogs"
        self.indexes_dir = self.data_dir / "indexes"
        self.profiles_dir = self.config_dir / "profiles"
        for path in (self.uploads_dir, self.tasks_dir, self.results_dir, self.catalogs_dir, self.indexes_dir, self.profiles_dir):
            path.mkdir(parents=True, exist_ok=True)

    def save_upload(self, original_name: str, payload: bytes, role: str) -> UploadRecord:
        suffix = Path(original_name).suffix.lower()
        if suffix not in {".xlsx", ".xlsm", ".csv"}:
            suffix = ".bin"
        file_id = uuid.uuid4().hex
        stored_name = f"{file_id}{suffix}"
        path = self.uploads_dir / stored_name
        path.write_bytes(payload)
        record = UploadRecord(
            file_id=file_id,
            role=role,
            original_name=original_name,
            stored_name=stored_name,
            size=len(payload),
            created_at=time.time(),
            path=str(path),
        )
        self._write_json(self.uploads_dir / f"{file_id}.json", asdict(record))
        return record

    def get_upload(self, file_id: str) -> UploadRecord:
        meta = self.uploads_dir / f"{_safe_name(file_id)}.json"
        if not meta.exists():
            raise FileNotFoundError(file_id)
        data = json.loads(meta.read_text(encoding="utf-8"))
        record = UploadRecord(**data)
        if not Path(record.path).exists():
            raise FileNotFoundError(record.path)
        return record

    def list_uploads(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for meta in self.uploads_dir.glob("*.json"):
            try:
                data = json.loads(meta.read_text(encoding="utf-8"))
                data["exists"] = Path(data.get("path", "")).exists()
                records.append(data)
            except Exception:
                continue
        return sorted(records, key=lambda item: item.get("created_at", 0), reverse=True)

    def delete_upload(self, file_id: str) -> bool:
        try:
            record = self.get_upload(file_id)
        except FileNotFoundError:
            return False
        path = Path(record.path)
        if path.exists() and self.uploads_dir.resolve() in path.resolve().parents:
            path.unlink(missing_ok=True)
        (self.uploads_dir / f"{_safe_name(file_id)}.json").unlink(missing_ok=True)
        return True

    def cleanup_uploads(self, older_than_seconds: int | None = None) -> dict[str, int]:
        now = time.time()
        deleted = 0
        bytes_deleted = 0
        for item in self.list_uploads():
            age = now - float(item.get("created_at", now))
            if older_than_seconds is not None and age < older_than_seconds:
                continue
            bytes_deleted += int(item.get("size", 0))
            if self.delete_upload(str(item["file_id"])):
                deleted += 1
        return {"deleted": deleted, "bytes_deleted": bytes_deleted}

    def create_catalog_from_upload(self, name: str, upload: UploadRecord) -> dict[str, Any]:
        catalog_id = f"{_safe_name(name, 'catalog')}-{int(time.time() * 1000)}"
        root = self.catalogs_dir / catalog_id
        root.mkdir(parents=True, exist_ok=False)
        suffix = Path(upload.original_name).suffix.lower() or ".xlsx"
        data_path = root / f"source{suffix}"
        shutil.copy2(upload.path, data_path)
        metadata = {
            "catalog_id": catalog_id,
            "name": name,
            "original_name": upload.original_name,
            "size": data_path.stat().st_size,
            "created_at": time.time(),
            "path": str(data_path),
            "index_status": "NOT_BUILT",
        }
        self._write_json(root / "catalog.json", metadata)
        return metadata

    def list_catalogs(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for meta in self.catalogs_dir.glob("*/catalog.json"):
            try:
                items.append(json.loads(meta.read_text(encoding="utf-8")))
            except Exception:
                continue
        return sorted(items, key=lambda item: item.get("created_at", 0), reverse=True)

    def get_catalog(self, catalog_id: str) -> dict[str, Any]:
        path = self.catalogs_dir / _safe_name(catalog_id) / "catalog.json"
        if not path.exists():
            raise FileNotFoundError(catalog_id)
        data = json.loads(path.read_text(encoding="utf-8"))
        if not Path(data.get("path", "")).exists():
            raise FileNotFoundError(data.get("path", ""))
        return data

    def update_catalog(self, catalog_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        current = self.get_catalog(catalog_id)
        current.update(changes)
        self._write_json(self.catalogs_dir / _safe_name(catalog_id) / "catalog.json", current)
        return current

    def publish_profile(self, name: str, document: dict[str, Any]) -> dict[str, Any]:
        profile_name = _safe_name(name, "profile")
        profile_dir = self.profiles_dir / profile_name
        profile_dir.mkdir(parents=True, exist_ok=True)
        timestamp = int(time.time() * 1000)
        version_name = f"v{timestamp}.yaml"
        version_path = profile_dir / version_name
        serialized = yaml.safe_dump(document, allow_unicode=True, sort_keys=False)
        version_path.write_text(serialized, encoding="utf-8")
        current_path = profile_dir / "current.yaml"
        current_path.write_text(serialized, encoding="utf-8")
        metadata = {
            "name": profile_name,
            "version": version_name.removesuffix(".yaml"),
            "published_at": time.time(),
            "path": str(current_path),
            "catalog_id": document.get("runtime", {}).get("target_catalog_id"),
        }
        self._write_json(profile_dir / "current.json", metadata)
        return metadata

    def list_profiles(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for meta in self.profiles_dir.glob("*/current.json"):
            try:
                items.append(json.loads(meta.read_text(encoding="utf-8")))
            except Exception:
                continue
        return sorted(items, key=lambda item: item.get("published_at", 0), reverse=True)

    def profile_versions(self, name: str) -> list[dict[str, Any]]:
        profile_dir = self.profiles_dir / _safe_name(name)
        if not profile_dir.exists():
            return []
        items = []
        for path in sorted(profile_dir.glob("v*.yaml"), reverse=True):
            items.append({"version": path.stem, "path": str(path), "size": path.stat().st_size})
        return items

    def load_profile_document(self, name: str, version: str | None = None) -> dict[str, Any]:
        profile_dir = self.profiles_dir / _safe_name(name)
        path = profile_dir / (f"{_safe_name(version)}.yaml" if version else "current.yaml")
        if not path.exists():
            raise FileNotFoundError(name)
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("profile root must be mapping")
        return raw

    def create_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        task_id = uuid.uuid4().hex[:16]
        task = {
            "task_id": task_id,
            "status": "PENDING",
            "created_at": time.time(),
            "updated_at": time.time(),
            **payload,
        }
        self.save_task(task)
        return task

    def save_task(self, task: dict[str, Any]) -> None:
        task["updated_at"] = time.time()
        self._write_json(self.tasks_dir / f"{_safe_name(str(task['task_id']))}.json", task)

    def get_task(self, task_id: str) -> dict[str, Any]:
        path = self.tasks_dir / f"{_safe_name(task_id)}.json"
        if not path.exists():
            raise FileNotFoundError(task_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def list_tasks(self) -> list[dict[str, Any]]:
        tasks: list[dict[str, Any]] = []
        for path in self.tasks_dir.glob("*.json"):
            try:
                tasks.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue
        return sorted(tasks, key=lambda item: item.get("created_at", 0), reverse=True)

    def result_path(self, task_id: str) -> Path:
        return self.results_dir / f"{_safe_name(task_id)}.xlsx"

    @staticmethod
    def _write_json(path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
