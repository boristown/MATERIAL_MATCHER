from __future__ import annotations

from fastapi.testclient import TestClient


def test_dictionary_api_creates_immutable_versions(authed: TestClient) -> None:
    created = authed.post(
        "/api/dictionaries",
        json={"name": "材质同义词", "mapping": {"SUS304": "304不锈钢"}, "case_sensitive": False},
    )
    assert created.status_code == 200
    dictionary_id = created.json()["dictionary_id"]
    assert created.json()["latest"]["version_no"] == 1

    listed = authed.get("/api/dictionaries")
    assert listed.status_code == 200
    assert listed.json()[0]["entry_count"] == 1

    version = authed.post(
        f"/api/dictionaries/{dictionary_id}/versions",
        json={"mapping": {"SUS304": "不锈钢304", "SUS316": "316不锈钢"}, "case_sensitive": True},
    )
    assert version.status_code == 200
    assert version.json()["version_no"] == 2

    versions = authed.get(f"/api/dictionaries/{dictionary_id}/versions")
    assert versions.status_code == 200
    assert [item["version_no"] for item in versions.json()] == [2, 1]
    assert versions.json()[1]["document"]["mapping"] == {"SUS304": "304不锈钢"}


def test_dictionary_api_rejects_empty_mapping(authed: TestClient) -> None:
    response = authed.post("/api/dictionaries", json={"name": "空字典", "mapping": {}})
    assert response.status_code == 422


def test_synonym_version_save_detects_concurrent_update(authed: TestClient) -> None:
    created = authed.post("/api/dictionaries", json={"name": "同义词并发", "mapping": {"三极管": "晶体管"}})
    dictionary_id = created.json()["dictionary_id"]
    first = authed.post(
        f"/api/dictionaries/{dictionary_id}/versions",
        json={"mapping": {"三极管": "晶体管", "光耦": "光电耦合器"}, "base_version_no": 1},
    )
    assert first.status_code == 200
    assert first.json()["version_no"] == 2
    stale = authed.post(
        f"/api/dictionaries/{dictionary_id}/versions",
        json={"mapping": {"三极管": "开关晶体管"}, "base_version_no": 1},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "DICTIONARY_VERSION_CONFLICT"
    assert stale.json()["error"]["details"]["current_version_no"] == 2
    current = authed.post(
        f"/api/dictionaries/{dictionary_id}/versions",
        json={"mapping": {"三极管": "开关晶体管"}, "base_version_no": 2},
    )
    assert current.status_code == 200
    assert current.json()["version_no"] == 3


def test_synonym_versions_record_operator_and_keep_history_readonly(authed: TestClient) -> None:
    created = authed.post("/api/dictionaries", json={"name": "同义词归属", "mapping": {"贴片": "表面贴装"}})
    dictionary_id = created.json()["dictionary_id"]
    authed.post(f"/api/dictionaries/{dictionary_id}/versions", json={"mapping": {"贴片": "表面贴装", "塑封": "塑料封装"}})
    versions = authed.get(f"/api/dictionaries/{dictionary_id}/versions").json()
    assert [v["version_no"] for v in versions] == [2, 1]
    assert versions[0]["created_by"] == versions[1]["created_by"] == "admin"
    immutable = authed.put(
        f"/api/dictionaries/{dictionary_id}/versions/1",
        json={"mapping": {"贴片": "被篡改"}},
    )
    assert immutable.status_code == 404 or immutable.status_code == 405
    assert versions[1]["document"]["mapping"] == {"贴片": "表面贴装"}
