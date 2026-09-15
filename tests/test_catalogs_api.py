from __future__ import annotations

from fastapi.testclient import TestClient


def _upload_target(authed: TestClient, name: str, code: str) -> str:
    response = authed.post(
        "/api/files/upload",
        data={"role": "target"},
        files={"file": (name, f"集团码,物料描述\n{code},测试物料\n".encode("utf-8"), "text/csv")},
    )
    assert response.status_code == 200
    return str(response.json()["file"]["file_id"])


def test_catalog_api_version_and_activation_lifecycle(authed: TestClient) -> None:
    file_v1 = _upload_target(authed, "catalog-v1.csv", "G001")
    created = authed.post(
        "/api/catalogs",
        json={"name": "集团目录", "source_file_id": file_v1, "group_code_column": "集团码"},
    )
    assert created.status_code == 200
    v1 = created.json()
    catalog_id = v1["catalog_id"]
    assert v1["active"] == 1

    file_v2 = _upload_target(authed, "catalog-v2.csv", "G002")
    added = authed.post(
        f"/api/catalogs/{catalog_id}/versions",
        json={"source_file_id": file_v2, "group_code_column": "集团码", "activate": False},
    )
    assert added.status_code == 200
    v2 = added.json()
    assert v2["active"] == 0

    history = authed.get(f"/api/catalogs/{catalog_id}/versions")
    assert history.status_code == 200
    assert len(history.json()) == 2
    assert sum(int(row["active"]) for row in history.json()) == 1

    activated = authed.post(f"/api/catalogs/{catalog_id}/versions/{v2['version_id']}/activate")
    assert activated.status_code == 200
    assert activated.json()["active"] == 1

    history_after = authed.get(f"/api/catalogs/{catalog_id}/versions").json()
    active_versions = [row for row in history_after if row["active"]]
    assert [row["version_id"] for row in active_versions] == [v2["version_id"]]

    fetched = authed.get(f"/api/catalogs/versions/{v1['version_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["active"] == 0


def test_catalog_version_api_rejects_foreign_version_activation(authed: TestClient) -> None:
    first_file = _upload_target(authed, "one.csv", "G001")
    second_file = _upload_target(authed, "two.csv", "G002")
    first = authed.post("/api/catalogs", json={"name": "目录一", "source_file_id": first_file, "group_code_column": "集团码"}).json()
    second = authed.post("/api/catalogs", json={"name": "目录二", "source_file_id": second_file, "group_code_column": "集团码"}).json()

    response = authed.post(f"/api/catalogs/{first['catalog_id']}/versions/{second['version_id']}/activate")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CATALOG_VERSION_NOT_FOUND"
