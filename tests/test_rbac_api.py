from __future__ import annotations

from fastapi.testclient import TestClient


def _create_user(authed: TestClient, username: str, role: str, password: str) -> None:
    response = authed.post('/api/users', json={'username': username, 'password': password, 'role': role})
    assert response.status_code == 200


def _login(client: TestClient, username: str, password: str) -> dict:
    client.post('/api/auth/logout')
    response = client.post('/api/auth/login', json={'username': username, 'password': password})
    assert response.status_code == 200
    return response.json()


def test_viewer_is_read_only_and_operator_can_create_task_draft(authed: TestClient) -> None:
    _create_user(authed, 'viewer1', 'viewer', 'Viewer12345')
    authed.post('/api/users/viewer1/reset-password', json={'password': 'Viewer12345', 'must_change_password': False})
    _login(authed, 'viewer1', 'Viewer12345')
    assert authed.get('/api/tasks').status_code == 200
    denied = authed.post('/api/task-drafts', json={'name': 'viewer不得创建'})
    assert denied.status_code == 403
    assert denied.json()['error']['code'] == 'PERMISSION_DENIED'
    assert authed.get('/api/users').status_code == 403

    _login(authed, 'admin', 'Ab3dEf7Gh9')
    _create_user(authed, 'operator1', 'operator', 'Operator12345')
    authed.post('/api/users/operator1/reset-password', json={'password': 'Operator12345', 'must_change_password': False})
    _login(authed, 'operator1', 'Operator12345')
    created = authed.post('/api/task-drafts', json={'name': 'operator可创建'})
    assert created.status_code == 200


def test_reviewer_can_review_but_cannot_create_configuration(authed: TestClient) -> None:
    _create_user(authed, 'reviewer1', 'reviewer', 'Reviewer12345')
    authed.post('/api/users/reviewer1/reset-password', json={'password': 'Reviewer12345', 'must_change_password': False})
    _login(authed, 'reviewer1', 'Reviewer12345')

    denied = authed.post('/api/task-drafts', json={'name': 'reviewer不得创建'})
    assert denied.status_code == 403
    review_request = authed.post('/api/tasks/missing/items/row1/reject', json={'comment': ''})
    assert review_request.status_code != 403


def test_forced_password_change_allows_only_auth_actions_until_changed(authed: TestClient) -> None:
    _create_user(authed, 'forced1', 'viewer', 'Initial12345')
    login = _login(authed, 'forced1', 'Initial12345')
    assert login['user']['must_change_password'] is True
    blocked = authed.get('/api/tasks')
    assert blocked.status_code == 403
    assert blocked.json()['error']['code'] == 'PASSWORD_CHANGE_REQUIRED'
    assert authed.get('/api/auth/me').status_code == 200

    changed = authed.post('/api/auth/change-password', json={'current_password': 'Initial12345', 'new_password': 'Changed12345'})
    assert changed.status_code == 200
    assert changed.json()['relogin_required'] is True
    assert authed.get('/api/tasks').status_code == 401
    relogin = authed.post('/api/auth/login', json={'username': 'forced1', 'password': 'Changed12345'})
    assert relogin.status_code == 200
    assert relogin.json()['user']['must_change_password'] is False
    assert authed.get('/api/tasks').status_code == 200
