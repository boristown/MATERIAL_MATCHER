from __future__ import annotations
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from material_matcher.api.app import create_app
import os

os.environ.setdefault("MATERIAL_MATCHER_SYNC_FREEZE", "1")  # legacy tests expect synchronous freeze inside POST /start
from material_matcher.settings import Settings

BOOTSTRAP_ADMIN_PASSWORD = 'Ab3dEf7Gh9'
TEST_ADMIN_PASSWORD = 'ChangedAdmin123'

@pytest.fixture()
def client(tmp_path: Path):
    settings=Settings(data_dir=tmp_path/'data',config_dir=tmp_path/'etc',log_dir=tmp_path/'log',admin_password=BOOTSTRAP_ADMIN_PASSWORD,worker_poll_seconds=0.01,embedding_model_root=tmp_path/'models',web_dist_dir=tmp_path/'web-dist')
    with TestClient(create_app(settings)) as test_client: yield test_client

@pytest.fixture()
def authed(client: TestClient)->TestClient:
    response=client.post('/api/auth/login',json={'username':'admin','password':BOOTSTRAP_ADMIN_PASSWORD}); assert response.status_code==200
    if response.json()['user']['must_change_password']:
        changed=client.post('/api/auth/change-password',json={'current_password':BOOTSTRAP_ADMIN_PASSWORD,'new_password':TEST_ADMIN_PASSWORD}); assert changed.status_code==200
        response=client.post('/api/auth/login',json={'username':'admin','password':TEST_ADMIN_PASSWORD}); assert response.status_code==200
    return client
