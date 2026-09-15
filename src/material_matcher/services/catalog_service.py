from __future__ import annotations

from datetime import datetime
from pathlib import Path
import uuid

from material_matcher.domain.errors import DomainError
from material_matcher.ingestion.inspector import inspect_tabular_file
from material_matcher.storage.files import FileRepository
from material_matcher.storage.metadata import MetadataRepository


def _now() -> str:
    return datetime.now().astimezone().isoformat()


class CatalogService:
    """Versioned Target catalog lifecycle.

    Catalog metadata is customer-agnostic. Each version points to one immutable
    uploaded Target file and explicitly records the group-code column. Exactly
    one READY version may be active per catalog.
    """

    def __init__(self, metadata: MetadataRepository, files: FileRepository) -> None:
        self.meta = metadata
        self.files = files

    def _catalog(self, catalog_id: str) -> dict[str, object]:
        with self.meta.connect() as connection:
            row = connection.execute("SELECT * FROM catalogs WHERE catalog_id=?", (catalog_id,)).fetchone()
        if row is None:
            raise DomainError("CATALOG_NOT_FOUND", "集团码目录不存在", status_code=404)
        return dict(row)

    def _validate_target(self, source_file_id: str, group_code_column: str) -> dict[str, object]:
        file_record = self.files.get(source_file_id)
        if file_record.get("role") != "target":
            raise DomainError("INVALID_FILE_ROLE", "集团码目录必须使用 target 文件", status_code=422)
        inspection = inspect_tabular_file(Path(str(file_record["stored_path"])))
        recommended = next(
            (sheet for sheet in inspection["sheets"] if sheet["sheet_name"] == inspection["recommended_sheet"]),
            None,
        )
        headers = {column["header"] for column in (recommended or {}).get("columns", [])}
        if group_code_column not in headers:
            raise DomainError(
                "COLUMN_NOT_FOUND",
                f"集团码字段“{group_code_column}”不存在",
                status_code=422,
            )
        return file_record

    def create(self, name: str, source_file_id: str, group_code_column: str) -> dict[str, object]:
        name = name.strip()
        if not name:
            raise DomainError("INVALID_CATALOG_NAME", "集团码目录名称不能为空", status_code=422)
        self._validate_target(source_file_id, group_code_column)
        catalog_id = uuid.uuid4().hex
        created_at = _now()
        with self.meta.connect() as connection:
            connection.execute("INSERT INTO catalogs VALUES(?,?,?)", (catalog_id, name, created_at))
        return self.add_version(
            catalog_id,
            source_file_id=source_file_id,
            group_code_column=group_code_column,
            activate=True,
        )

    def add_version(
        self,
        catalog_id: str,
        *,
        source_file_id: str,
        group_code_column: str,
        activate: bool = False,
    ) -> dict[str, object]:
        self._catalog(catalog_id)
        self._validate_target(source_file_id, group_code_column)
        version_id = uuid.uuid4().hex
        created_at = _now()
        with self.meta.connect() as connection:
            if activate:
                connection.execute("UPDATE catalog_versions SET active=0 WHERE catalog_id=?", (catalog_id,))
            connection.execute(
                "INSERT INTO catalog_versions VALUES(?,?,?,?,?,?,?)",
                (version_id, catalog_id, source_file_id, group_code_column, "READY", 1 if activate else 0, created_at),
            )
            connection.execute(
                "INSERT INTO audit_events VALUES(?,?,?,?,?,?)",
                (
                    uuid.uuid4().hex,
                    "catalog",
                    catalog_id,
                    "CATALOG_VERSION_CREATED",
                    f'{{"version_id":"{version_id}","active":{str(bool(activate)).lower()}}}',
                    created_at,
                ),
            )
        return self.version(version_id)

    def activate(self, catalog_id: str, version_id: str) -> dict[str, object]:
        self._catalog(catalog_id)
        version = self.version(version_id)
        if version.get("catalog_id") != catalog_id:
            raise DomainError("CATALOG_VERSION_NOT_FOUND", "集团码目录版本不存在", status_code=404)
        if version.get("status") != "READY":
            raise DomainError("CATALOG_NOT_READY", "只有 READY 的集团码目录版本才能激活", status_code=409)
        changed_at = _now()
        with self.meta.connect() as connection:
            connection.execute("UPDATE catalog_versions SET active=0 WHERE catalog_id=?", (catalog_id,))
            connection.execute("UPDATE catalog_versions SET active=1 WHERE version_id=?", (version_id,))
            connection.execute(
                "INSERT INTO audit_events VALUES(?,?,?,?,?,?)",
                (
                    uuid.uuid4().hex,
                    "catalog",
                    catalog_id,
                    "CATALOG_VERSION_ACTIVATED",
                    f'{{"version_id":"{version_id}"}}',
                    changed_at,
                ),
            )
        return self.version(version_id)

    def version(self, version_id: str) -> dict[str, object]:
        with self.meta.connect() as connection:
            row = connection.execute(
                "SELECT c.name, v.* FROM catalog_versions v JOIN catalogs c ON c.catalog_id=v.catalog_id WHERE v.version_id=?",
                (version_id,),
            ).fetchone()
        if row is None:
            raise DomainError("CATALOG_VERSION_NOT_FOUND", "集团码目录版本不存在", status_code=404)
        return dict(row)

    def versions(self, catalog_id: str) -> list[dict[str, object]]:
        self._catalog(catalog_id)
        with self.meta.connect() as connection:
            rows = connection.execute(
                "SELECT c.name, v.* FROM catalog_versions v JOIN catalogs c ON c.catalog_id=v.catalog_id WHERE v.catalog_id=? ORDER BY v.created_at DESC",
                (catalog_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_versions(self) -> list[dict[str, object]]:
        with self.meta.connect() as connection:
            rows = connection.execute(
                "SELECT c.name, v.* FROM catalog_versions v JOIN catalogs c ON c.catalog_id=v.catalog_id ORDER BY v.created_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]
