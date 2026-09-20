from __future__ import annotations

from fastapi.testclient import TestClient


def _single_document() -> dict[str, object]:
    return {
        "source_id_column": "物料编码",
        "scope_mode": "GLOBAL",
        "rules": [
            {
                "id": "name",
                "source": {"fields": ["物料名称"]},
                "target": {"fields": ["集团物料名称"]},
                "matcher": "fuzzy",
                "weight": 100,
            }
        ],
        "retrieval": {"mode": "scan"},
    }


def _composite_document(
    child_refs: list[dict[str, object]],
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
        "retrieval": {"mode": "scan"},
        "advanced": {
            "profile_kind": "composite",
            "composite_children": child_refs,
        },
    }


def _create_published_single(client: TestClient, name: str) -> str:
    created = client.post("/api/profiles", json={"name": name, "document": _single_document()})
    assert created.status_code == 200, created.text
    profile_id = created.json()["profile_id"]
    published = client.post(f"/api/profiles/{profile_id}/publish")
    assert published.status_code == 200, published.text
    return profile_id


def test_composite_profile_api_get_versions_validate_publish_and_rollback(authed: TestClient) -> None:
    child1 = _create_published_single(authed, "方案1")
    child2 = _create_published_single(authed, "方案2")
    refs = [
        {"profile_id": child1, "version_no": 1},
        {"profile_id": child2, "version_no": 1},
    ]

    created = authed.post(
        "/api/profiles",
        json={"name": "A007 物资类其他（跨类目）", "document": _composite_document(refs)},
    )
    assert created.status_code == 200, created.text
    composite_id = created.json()["profile_id"]

    validated = authed.post(f"/api/profiles/{composite_id}/validate")
    assert validated.status_code == 200, validated.text
    assert validated.json()["normalized"]["advanced"]["composite_children"] == refs

    published_v1 = authed.post(f"/api/profiles/{composite_id}/publish")
    assert published_v1.status_code == 200, published_v1.text
    assert published_v1.json()["version_no"] == 1
    assert published_v1.json()["document"]["rules"] == []
    assert published_v1.json()["document"]["advanced"]["composite_children"] == refs

    fetched = authed.get(f"/api/profiles/{composite_id}")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["latest_published"]["document"]["advanced"]["composite_children"] == refs

    updated = _composite_document(refs, filter_value="A007-V2")
    saved = authed.put(f"/api/profiles/{composite_id}/draft", json=updated)
    assert saved.status_code == 200, saved.text
    published_v2 = authed.post(f"/api/profiles/{composite_id}/publish")
    assert published_v2.status_code == 200, published_v2.text
    assert published_v2.json()["version_no"] == 2

    versions = authed.get(f"/api/profiles/{composite_id}/versions")
    assert versions.status_code == 200, versions.text
    assert [item["version_no"] for item in versions.json()] == [2, 1]
    assert versions.json()[1]["document"]["advanced"]["composite_children"] == refs

    rolled = authed.post(f"/api/profiles/{composite_id}/rollback/1")
    assert rolled.status_code == 200, rolled.text
    assert rolled.json()["version_no"] == 3
    assert rolled.json()["document"]["source_filter"]["values"] == ["A007"]
    assert rolled.json()["document"]["advanced"]["composite_children"] == refs
