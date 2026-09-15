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
