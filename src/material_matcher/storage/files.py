from __future__ import annotations

from datetime import datetime
import hashlib
from pathlib import Path
import os
from typing import BinaryIO
import uuid

from material_matcher.domain.errors import DomainError
from material_matcher.storage.metadata import MetadataRepository

_ALLOWED_SUFFIXES = {".xlsx", ".xlsm", ".csv"}


class FileRepository:
    def __init__(self, root: Path, metadata: MetadataRepository) -> None:
        self.root = root
        self.meta = metadata
        (root / "uploads").mkdir(parents=True, exist_ok=True)
        (root / "tmp").mkdir(parents=True, exist_ok=True)

    def save_stream(
        self,
        original_name: str,
        role: str,
        stream: BinaryIO,
        max_bytes: int,
    ) -> dict[str, object]:
        suffix = Path(original_name).suffix.lower()
        if suffix == ".xls":
            raise DomainError(
                "UNSUPPORTED_FILE",
                "暂不支持 .xls，请先转换为 .xlsx",
                status_code=400,
            )
        if suffix not in _ALLOWED_SUFFIXES:
            raise DomainError(
                "UNSUPPORTED_FILE",
                "仅支持 .xlsx / .xlsm / .csv",
                status_code=400,
            )

        file_id = uuid.uuid4().hex
        temporary_path = self.root / "tmp" / f"{file_id}{suffix}.part"
        digest = hashlib.sha256()
        size_bytes = 0
        try:
            with temporary_path.open("wb") as output:
                while chunk := stream.read(1024 * 1024):
                    size_bytes += len(chunk)
                    if size_bytes > max_bytes:
                        raise DomainError(
                            "FILE_TOO_LARGE",
                            "文件超过当前上传上限，请使用分块上传",
                            status_code=413,
                        )
                    digest.update(chunk)
                    output.write(chunk)
            final_path = self.root / "uploads" / f"{file_id}{suffix}"
            os.replace(temporary_path, final_path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise

        created_at = datetime.now().astimezone().isoformat()
        with self.meta.connect() as connection:
            connection.execute(
                "INSERT INTO files VALUES(?,?,?,?,?,?,?,?)",
                (
                    file_id,
                    role,
                    original_name,
                    str(final_path),
                    size_bytes,
                    digest.hexdigest(),
                    "READY",
                    created_at,
                ),
            )
        return self.get(file_id)

    def get(self, file_id: str) -> dict[str, object]:
        with self.meta.connect() as connection:
            row = connection.execute(
                "SELECT * FROM files WHERE file_id=?", (file_id,)
            ).fetchone()
        if row is None:
            raise DomainError("FILE_NOT_FOUND", "文件不存在或已清理", status_code=404)
        return dict(row)

    def list(self) -> list[dict[str, object]]:
        with self.meta.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM files ORDER BY created_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]
