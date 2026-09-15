from __future__ import annotations

from pathlib import Path

import pytest

from material_matcher.domain.errors import DomainError
from material_matcher.security.users import UserService
from material_matcher.storage.metadata import MetadataRepository


def test_bootstrap_admin_and_password_hash_are_persisted_without_plaintext(tmp_path: Path) -> None:
    meta = MetadataRepository(tmp_path / "meta.db")
    users = UserService(meta)
    users.ensure_bootstrap_admin("Ab3dEf7Gh9")
    principal = users.authenticate("admin", "Ab3dEf7Gh9")
    assert principal["role"] == "admin"
    assert principal["must_change_password"] is True
    with meta.connect() as connection:
        row = connection.execute("SELECT password_hash,salt FROM users WHERE username='admin'").fetchone()
    assert row["password_hash"] != "Ab3dEf7Gh9"
    assert len(str(row["salt"])) == 32

    with pytest.raises(DomainError) as exc:
        users.set_password("admin", "Ab3dEf7Gh9")
    assert exc.value.code == "PASSWORD_REUSE"
    changed = users.set_password("admin", "ChangedAdmin123")
    assert changed["must_change_password"] is False
    assert users.authenticate("admin", "ChangedAdmin123")["role"] == "admin"


def test_user_roles_password_policy_and_last_admin_guard(tmp_path: Path) -> None:
    meta = MetadataRepository(tmp_path / "meta.db")
    users = UserService(meta)
    users.ensure_bootstrap_admin("Ab3dEf7Gh9")
    users.set_password("admin", "ChangedAdmin123")
    viewer = users.create("viewer1", "View123456", "viewer")
    assert viewer["must_change_password"] is True
    assert users.authenticate("viewer1", "View123456")["role"] == "viewer"

    with pytest.raises(DomainError) as exc:
        users.create("weak", "short", "operator")
    assert exc.value.code == "WEAK_PASSWORD"

    with pytest.raises(DomainError) as exc:
        users.update("admin", enabled=False)
    assert exc.value.code == "LAST_ADMIN_REQUIRED"

    users.create("admin2", "Admin234567", "admin")
    disabled = users.update("admin", enabled=False)
    assert disabled["enabled"] is False
