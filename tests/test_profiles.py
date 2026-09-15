from __future__ import annotations

from pathlib import Path

import pytest

from material_matcher.domain.errors import DomainError
from material_matcher.services.profile_service import ProfileService
from material_matcher.storage.metadata import MetadataRepository


def _document(weight: int = 80) -> dict[str, object]:
    return {
        "source_id_column": "物料号",
        "scope_mode": "GLOBAL",
        "rules": [
            {
                "id": "desc",
                "source": {"fields": ["物料描述"], "combine": "concat", "separator": " ", "pipeline": []},
                "target": {"fields": ["集团描述"], "combine": "concat", "separator": " ", "pipeline": []},
                "matcher": "fuzzy",
                "weight": weight,
                "critical": False,
            }
        ],
        "decision": {"success_threshold": 88, "review_enabled": True, "review_threshold": 75, "top_n": 5},
        "retrieval": {"mode": "auto", "retrieval_top_k": 200, "oversample": 4},
    }


def test_profile_publish_and_rollback_create_immutable_versions(tmp_path: Path) -> None:
    meta = MetadataRepository(tmp_path / "meta.db")
    service = ProfileService(meta)
    profile = service.create("通用物料方案", _document())
    profile_id = str(profile["profile_id"])

    validated = service.validate(profile_id)
    assert validated["ok"] is True

    v1 = service.publish(profile_id)
    assert v1["version_no"] == 1
    assert v1["status"] == "PUBLISHED"
    v1_sha = v1["sha256"]

    service.save_draft(profile_id, _document(weight=60))
    v2 = service.publish(profile_id)
    assert v2["version_no"] == 2
    assert v2["sha256"] != v1_sha

    rollback = service.rollback(profile_id, 1)
    assert rollback["version_no"] == 3
    assert rollback["sha256"] == v1_sha
    assert service.version(profile_id, 1)["sha256"] == v1_sha

    versions = service.versions(profile_id)
    assert [item["version_no"] for item in versions] == [3, 2, 1]
    listed = service.list()[0]
    assert listed["latest_published_version"] == 3
    assert listed["has_draft"] == 0


def test_profile_edit_after_publish_uses_new_draft_without_mutating_version(tmp_path: Path) -> None:
    meta = MetadataRepository(tmp_path / "meta.db")
    service = ProfileService(meta)
    profile_id = str(service.create("方案A", _document())["profile_id"])
    v1 = service.publish(profile_id)

    current = service.save_draft(profile_id, _document(weight=40))
    assert current["draft"]["version_no"] == 0
    assert current["latest_published"]["version_no"] == 1
    assert service.version(profile_id, 1)["sha256"] == v1["sha256"]


def test_profile_validation_rejects_incomplete_business_config(tmp_path: Path) -> None:
    meta = MetadataRepository(tmp_path / "meta.db")
    service = ProfileService(meta)
    profile_id = str(service.create("空方案", {})["profile_id"])
    with pytest.raises(DomainError) as exc:
        service.validate(profile_id)
    assert exc.value.code == "INVALID_PROFILE"


def test_profile_rollback_rejects_missing_version(tmp_path: Path) -> None:
    meta = MetadataRepository(tmp_path / "meta.db")
    service = ProfileService(meta)
    profile_id = str(service.create("方案B", _document())["profile_id"])
    with pytest.raises(DomainError) as exc:
        service.rollback(profile_id, 99)
    assert exc.value.code == "PROFILE_VERSION_NOT_FOUND"
