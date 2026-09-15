from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from material_matcher.domain.errors import DomainError
from material_matcher.services.catalog_service import CatalogService
from material_matcher.storage.files import FileRepository
from material_matcher.storage.metadata import MetadataRepository


def _target(files: FileRepository, name: str, code: str) -> str:
    payload = f"集团码,物料描述\n{code},测试物料\n".encode("utf-8")
    record = files.save_stream(name, "target", BytesIO(payload), 1024 * 1024)
    return str(record["file_id"])


def test_catalog_versions_are_immutable_and_activation_is_exclusive(tmp_path: Path) -> None:
    meta = MetadataRepository(tmp_path / "meta.db")
    files = FileRepository(tmp_path / "data", meta)
    service = CatalogService(meta, files)

    first_file = _target(files, "target-v1.csv", "G001")
    first = service.create("集团目录", first_file, "集团码")
    catalog_id = str(first["catalog_id"])
    assert first["active"] == 1

    second_file = _target(files, "target-v2.csv", "G002")
    second = service.add_version(
        catalog_id,
        source_file_id=second_file,
        group_code_column="集团码",
        activate=False,
    )
    assert second["active"] == 0
    assert service.version(str(first["version_id"]))["active"] == 1

    activated = service.activate(catalog_id, str(second["version_id"]))
    assert activated["active"] == 1
    assert service.version(str(first["version_id"]))["active"] == 0
    versions = service.versions(catalog_id)
    assert {str(row["source_file_id"]) for row in versions} == {first_file, second_file}
    assert sum(int(row["active"]) for row in versions) == 1


def test_catalog_rejects_non_target_file_and_missing_group_code_column(tmp_path: Path) -> None:
    meta = MetadataRepository(tmp_path / "meta.db")
    files = FileRepository(tmp_path / "data", meta)
    service = CatalogService(meta, files)
    source = files.save_stream(
        "source.csv",
        "source",
        BytesIO("物料号,描述\nM1,测试\n".encode("utf-8")),
        1024 * 1024,
    )
    with pytest.raises(DomainError) as wrong_role:
        service.create("错误目录", str(source["file_id"]), "物料号")
    assert wrong_role.value.code == "INVALID_FILE_ROLE"

    target_file = _target(files, "target.csv", "G001")
    with pytest.raises(DomainError) as missing_column:
        service.create("错误字段", target_file, "不存在字段")
    assert missing_column.value.code == "COLUMN_NOT_FOUND"
