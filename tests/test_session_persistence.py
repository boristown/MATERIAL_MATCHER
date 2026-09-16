from __future__ import annotations

import time
from pathlib import Path

from material_matcher.security.session import SessionStore
from material_matcher.storage.metadata import MetadataRepository


def test_sessions_survive_store_recreation(tmp_path: Path) -> None:
    db = tmp_path / "meta.db"
    first = SessionStore(MetadataRepository(db), 3600)
    session = first.create("operator", "operator")
    # 模拟服务重启:全新 store 实例读取同一数据库
    second = SessionStore(MetadataRepository(db), 3600)
    restored = second.get(session.token)
    assert restored is not None
    assert restored.username == "operator" and restored.role == "operator"
    second.revoke_user("operator")
    assert SessionStore(MetadataRepository(db), 3600).get(session.token) is None


def test_expired_sessions_are_rejected_and_purged(tmp_path: Path) -> None:
    db = tmp_path / "meta.db"
    store = SessionStore(MetadataRepository(db), 60)
    session = store.create("viewer", "viewer")
    assert store.get(session.token) is not None
    with MetadataRepository(db).connect() as connection:
        connection.execute("UPDATE sessions SET expires_at=? WHERE token=?", (time.time() - 1, session.token))
    assert store.get(session.token) is None
