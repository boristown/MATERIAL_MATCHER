import io
from pathlib import Path

import pytest

from material_matcher.storage.files import FileRepository
from material_matcher.storage.metadata import MetadataRepository


@pytest.fixture()
def store(tmp_path: Path):
    meta = MetadataRepository(tmp_path / "meta.db")
    root = tmp_path / "data"
    (root / "uploads").mkdir(parents=True)
    (root / "tmp").mkdir(parents=True)
    return FileRepository(root, meta), root


def test_identical_upload_reuses_stored_file(store):
    files, root = store
    payload = b"XLSX-BYTES-IDENTICAL" * 1024
    a = files.save_stream("集团标准码表.xlsx", "target", io.BytesIO(payload), 10 * 1024 * 1024)
    assert files.dedup_reused is False
    b = files.save_stream("同一文件换名再传.xlsx", "source", io.BytesIO(payload), 10 * 1024 * 1024)
    assert files.dedup_reused is True
    assert a["file_id"] != b["file_id"]
    assert str(a["stored_path"]) == str(b["stored_path"])
    assert int(b["size_bytes"]) == len(payload)
    stored = list((root / "uploads").iterdir())
    assert len(stored) == 1


def test_different_content_not_reused(store):
    files, root = store
    files.save_stream("a.xlsx", "target", io.BytesIO(b"AAA" * 100), 10 * 1024 * 1024)
    files.save_stream("b.xlsx", "target", io.BytesIO(b"BBB" * 100), 10 * 1024 * 1024)
    assert len(list((root / "uploads").iterdir())) == 2
