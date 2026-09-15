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
