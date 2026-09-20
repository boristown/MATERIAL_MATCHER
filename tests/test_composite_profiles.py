from __future__ import annotations

from pathlib import Path

import pytest

from material_matcher.domain.errors import DomainError
from material_matcher.services.profile_service import ProfileService
from material_matcher.storage.metadata import MetadataRepository


def _single_document(weight: int = 100) -> dict[str, object]:
    return {
        "source_id_column": "物料编码",
        "scope_mode": "GLOBAL",
        "rules": [
            {
                "id": "name",
                "source": {"fields": ["物料名称"]},
                "target": {"fields": ["集团物料名称"]},
                "matcher": "fuzzy",
                "weight": weight,
            }
        ],
        "decision": {
            "success_threshold": 88,
            "review_enabled": True,
            "review_threshold": 75,
            "top_n": 5,
        },
        "retrieval": {"mode": "scan"},
    }


def _composite_document(
    children: list[dict[str, object]],
    *,
    filter_value: str = "A007",
) -> dict[str, object]:
    return {
        "source_id_column": "物料编码",
        "source_filter": {
            "field": "物料类型",
            "values": [filter_value],
            "mode": "include",
            "match": "exact",
        },
        "scope_mode": "GLOBAL",
        "rules": [],
        "decision": {
            "success_threshold": 88,
            "review_enabled": True,
            "review_threshold": 75,
            "top_n": 5,
        },
        "retrieval": {"mode": "scan"},
        "advanced": {
            "profile_kind": "composite",
            "composite_children": children,
        },
    }


def _publish_single(service: ProfileService, name: str) -> tuple[str, dict[str, object]]:
    profile_id = str(service.create(name, _single_document())["profile_id"])
    return profile_id, service.publish(profile_id)


def _children(document: dict[str, object]) -> list[dict[str, object]]:
    advanced = document["advanced"]
    assert isinstance(advanced, dict)
    children = advanced["composite_children"]
    assert isinstance(children, list)
    return children


def test_create_ordinary_child_profile(tmp_path: Path) -> None:
    service = ProfileService(MetadataRepository(tmp_path / "meta.db"))
    created = service.create("方案1", _single_document())
    assert created["draft"]["document"]["rules"][0]["id"] == "name"


def test_publish_ordinary_child_profile(tmp_path: Path) -> None:
    service = ProfileService(MetadataRepository(tmp_path / "meta.db"))
    profile_id = str(service.create("方案1", _single_document())["profile_id"])
    published = service.publish(profile_id)
    assert published["status"] == "PUBLISHED"
    assert published["version_no"] == 1


def test_create_composite_allows_empty_top_level_rules(tmp_path: Path) -> None:
    service = ProfileService(MetadataRepository(tmp_path / "meta.db"))
    child1, _ = _publish_single(service, "方案1")
    child2, _ = _publish_single(service, "方案2")
    composite_id = str(
        service.create(
            "A007 物资类其他（跨类目）",
            _composite_document(
                [
                    {"profile_id": child1, "version_no": 1},
                    {"profile_id": child2, "version_no": 1},
                ]
            ),
        )["profile_id"]
    )

    validated = service.validate(composite_id)
    normalized = validated["normalized"]
    assert normalized["rules"] == []
    assert normalized["source_filter"]["values"] == ["A007"]
    assert normalized["advanced"]["profile_kind"] == "composite"


def test_composite_freezes_explicit_child_versions(tmp_path: Path) -> None:
    service = ProfileService(MetadataRepository(tmp_path / "meta.db"))
    child1, _ = _publish_single(service, "方案1")
    service.save_draft(child1, _single_document(weight=80))
    child1_v2 = service.publish(child1)
    child2, _ = _publish_single(service, "方案2")

    composite_id = str(
        service.create(
            "A007",
            _composite_document(
                [
                    {"profile_id": child1, "version_no": child1_v2["version_no"]},
                    {"profile_id": child2, "version_no": 1},
                ]
            ),
        )["profile_id"]
    )
    published = service.publish(composite_id)

    assert _children(published["document"]) == [
        {"profile_id": child1, "version_no": 2},
        {"profile_id": child2, "version_no": 1},
    ]


def test_new_child_version_does_not_change_old_composite(tmp_path: Path) -> None:
    service = ProfileService(MetadataRepository(tmp_path / "meta.db"))
    child1, _ = _publish_single(service, "方案1")
    child2, _ = _publish_single(service, "方案2")
    refs = [
        {"profile_id": child1, "version_no": 1},
        {"profile_id": child2, "version_no": 1},
    ]
    composite_id = str(service.create("A007", _composite_document(refs))["profile_id"])
    composite_v1 = service.publish(composite_id)

    service.save_draft(child1, _single_document(weight=70))
    service.publish(child1)

    assert _children(service.version(composite_id, 1)["document"]) == refs
    assert service.version(composite_id, 1)["sha256"] == composite_v1["sha256"]


def test_self_reference_is_rejected(tmp_path: Path) -> None:
    service = ProfileService(MetadataRepository(tmp_path / "meta.db"))
    other, _ = _publish_single(service, "方案2")
    composite_id = str(service.create("A007", {})["profile_id"])
    service.save_draft(
        composite_id,
        _composite_document(
            [
                {"profile_id": composite_id, "version_no": 1},
                {"profile_id": other, "version_no": 1},
            ]
        ),
    )

    with pytest.raises(DomainError) as exc:
        service.validate(composite_id)
    assert exc.value.code == "INVALID_PROFILE"
    assert "不能引用自身" in exc.value.message


def test_nested_composite_is_rejected(tmp_path: Path) -> None:
    service = ProfileService(MetadataRepository(tmp_path / "meta.db"))
    leaf1, _ = _publish_single(service, "方案1")
    leaf2, _ = _publish_single(service, "方案2")
    nested_id = str(
        service.create(
            "组合子方案",
            _composite_document(
                [
                    {"profile_id": leaf1, "version_no": 1},
                    {"profile_id": leaf2, "version_no": 1},
                ]
            ),
        )["profile_id"]
    )
    service.publish(nested_id)
    ordinary, _ = _publish_single(service, "方案3")
    parent_id = str(
        service.create(
            "A007",
            _composite_document(
                [
                    {"profile_id": nested_id, "version_no": 1},
                    {"profile_id": ordinary, "version_no": 1},
                ]
            ),
        )["profile_id"]
    )

    with pytest.raises(DomainError) as exc:
        service.publish(parent_id)
    assert exc.value.code == "INVALID_PROFILE"
    assert "不支持嵌套" in exc.value.message


def test_missing_published_child_version_is_rejected(tmp_path: Path) -> None:
    service = ProfileService(MetadataRepository(tmp_path / "meta.db"))
    unpublished_id = str(service.create("未发布方案", _single_document())["profile_id"])
    published_id, _ = _publish_single(service, "已发布方案")
    composite_id = str(
        service.create(
            "A007",
            _composite_document(
                [
                    {"profile_id": unpublished_id, "version_no": 1},
                    {"profile_id": published_id, "version_no": 1},
                ]
            ),
        )["profile_id"]
    )

    with pytest.raises(DomainError) as exc:
        service.validate(composite_id)
    assert exc.value.code == "INVALID_PROFILE"
    assert exc.value.details == {"profile_id": unpublished_id, "version_no": 1}


def test_rollback_preserves_original_child_version_references(tmp_path: Path) -> None:
    service = ProfileService(MetadataRepository(tmp_path / "meta.db"))
    child1, _ = _publish_single(service, "方案1")
    child2, _ = _publish_single(service, "方案2")
    refs_v1 = [
        {"profile_id": child1, "version_no": 1},
        {"profile_id": child2, "version_no": 1},
    ]
    composite_id = str(service.create("A007", _composite_document(refs_v1))["profile_id"])
    service.publish(composite_id)

    service.save_draft(child1, _single_document(weight=80))
    service.publish(child1)
    service.save_draft(child2, _single_document(weight=70))
    service.publish(child2)
    refs_v2 = [
        {"profile_id": child1, "version_no": 2},
        {"profile_id": child2, "version_no": 2},
    ]
    service.save_draft(composite_id, _composite_document(refs_v2, filter_value="A007-V2"))
    service.publish(composite_id)

    rolled_back = service.rollback(composite_id, 1)
    assert rolled_back["version_no"] == 3
    assert _children(rolled_back["document"]) == refs_v1
    assert rolled_back["document"]["source_filter"]["values"] == ["A007"]


def test_duplicate_profile_version_reference_is_rejected(tmp_path: Path) -> None:
    service = ProfileService(MetadataRepository(tmp_path / "meta.db"))
    child, _ = _publish_single(service, "方案1")
    composite_id = str(
        service.create(
            "A007",
            _composite_document(
                [
                    {"profile_id": child, "version_no": 1},
                    {"profile_id": child, "version_no": 1},
                ]
            ),
        )["profile_id"]
    )

    with pytest.raises(DomainError) as exc:
        service.validate(composite_id)
    assert exc.value.code == "INVALID_PROFILE"
    assert "不能重复引用" in exc.value.message
