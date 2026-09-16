from __future__ import annotations

from fastapi.testclient import TestClient


def _document(weight: int = 80) -> dict[str, object]:
    return {
        "source_id_column": "物料号",
        "scope_mode": "GLOBAL",
        "rules": [
            {
                "id": "desc",
                "source": {"fields": ["物料描述"]},
                "target": {"fields": ["集团描述"]},
                "matcher": "fuzzy",
                "weight": weight,
            }
        ],
        "decision": {"success_threshold": 88, "review_enabled": True, "review_threshold": 75, "top_n": 5},
        "retrieval": {"mode": "auto", "retrieval_top_k": 200, "oversample": 4},
    }


def test_profile_api_publish_edit_and_rollback(authed: TestClient) -> None:
    created = authed.post('/api/profiles', json={'name': '通用方案', 'document': _document()})
    assert created.status_code == 200
    profile_id = created.json()['profile_id']

    validated = authed.post(f'/api/profiles/{profile_id}/validate')
    assert validated.status_code == 200
    assert validated.json()['ok'] is True

    v1 = authed.post(f'/api/profiles/{profile_id}/publish')
    assert v1.status_code == 200
    assert v1.json()['version_no'] == 1

    saved = authed.put(f'/api/profiles/{profile_id}/draft', json=_document(55))
    assert saved.status_code == 200
    assert saved.json()['draft']['document']['rules'][0]['weight'] == 55

    v2 = authed.post(f'/api/profiles/{profile_id}/publish')
    assert v2.status_code == 200
    assert v2.json()['version_no'] == 2

    rolled = authed.post(f'/api/profiles/{profile_id}/rollback/1')
    assert rolled.status_code == 200
    assert rolled.json()['version_no'] == 3
    assert rolled.json()['document']['rules'][0]['weight'] == 80

    history = authed.get(f'/api/profiles/{profile_id}/versions')
    assert history.status_code == 200
    assert [item['version_no'] for item in history.json()] == [3, 2, 1]
    listed = authed.get('/api/profiles')
    assert listed.status_code == 200
    assert listed.json()[0]['latest_published_version'] == 3


def test_profile_api_rejects_invalid_draft_on_publish(authed: TestClient) -> None:
    created = authed.post('/api/profiles', json={'name': '待配置方案'})
    profile_id = created.json()['profile_id']
    invalid = authed.post(f'/api/profiles/{profile_id}/publish')
    assert invalid.status_code == 422
    assert invalid.json()['error']['code'] == 'INVALID_PROFILE'


def test_profile_rename_delete_and_reference_guard(tmp_path, authed) -> None:
    client = authed
    created = client.post("/api/profiles", json={"name": "待删方案", "document": None}).json()
    pid = created["profile_id"]
    renamed = client.patch(f"/api/profiles/{pid}", json={"name": "A001 测试方案"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "A001 测试方案"
    listing = client.get("/api/profiles").json()
    assert any(item["name"] == "A001 测试方案" for item in listing)
    deleted = client.delete(f"/api/profiles/{pid}")
    assert deleted.status_code == 200
    assert all(item["profile_id"] != pid for item in client.get("/api/profiles").json())

    # 被草稿引用后拒绝删除(真实引用链)
    target = tmp_path / "guard_target.csv"
    target.write_text("集团码,名称\nG1,电阻\n", encoding="utf-8")
    with target.open("rb") as stream:
        uploaded = client.post("/api/files/upload", data={"role": "target"}, files={"file": ("guard_target.csv", stream, "text/csv")}).json()
    catalog = client.post("/api/catalogs", json={"name": "防护目录", "source_file_id": uploaded["file"]["file_id"], "group_code_column": "集团码"}).json()
    doc = {
        "source_id_column": "编码", "scope_mode": "GLOBAL",
        "rules": [{"id": "n", "source": {"fields": ["名称"]}, "target": {"fields": ["名称"]}, "matcher": "exact", "weight": 100}],
        "decision": {"success_threshold": 88, "review_enabled": True, "review_threshold": 75, "top_n": 5},
        "retrieval": {"mode": "scan"},
    }
    p2 = client.post("/api/profiles", json={"name": "引用测试", "document": doc}).json()["profile_id"]
    client.post(f"/api/profiles/{p2}/validate").raise_for_status()
    client.post(f"/api/profiles/{p2}/publish").raise_for_status()
    source = tmp_path / "guard_source.csv"
    source.write_text("编码,名称\n0001,电阻\n", encoding="utf-8")
    with source.open("rb") as stream:
        sfile = client.post("/api/files/upload", data={"role": "source"}, files={"file": ("guard_source.csv", stream, "text/csv")}).json()
    draft = client.post("/api/task-drafts", json={"name": "引用草稿"}).json()["draft_id"]
    bound = client.put(f"/api/task-drafts/{draft}/data", json={
        "source_file_id": sfile["file"]["file_id"], "catalog_version_id": catalog["version_id"],
        "template_profile_id": p2, "template_profile_version": 1,
    })
    assert bound.status_code == 200, bound.text
    resp = client.delete(f"/api/profiles/{p2}")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "PROFILE_IN_USE"
