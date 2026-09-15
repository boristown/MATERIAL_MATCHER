from __future__ import annotations

from datetime import datetime
import hashlib
import hmac
import os
from typing import Literal

from material_matcher.domain.errors import DomainError
from material_matcher.storage.metadata import MetadataRepository

Role = Literal["admin", "operator", "reviewer", "viewer"]
ROLES: tuple[Role, ...] = ("admin", "operator", "reviewer", "viewer")


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def _derive(password: str, salt: bytes) -> str:
    # stdlib-only KDF so offline deployments do not gain another wheel dependency.
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32).hex()


def _new_secret(password: str) -> tuple[str, str]:
    salt = os.urandom(16)
    return salt.hex(), _derive(password, salt)


class UserService:
    def __init__(self, metadata: MetadataRepository) -> None:
        self.meta = metadata

    def ensure_bootstrap_admin(self, password: str | None) -> None:
        if not password:
            return
        with self.meta.connect() as connection:
            existing = connection.execute("SELECT username FROM users WHERE username='admin'").fetchone()
            if existing is not None:
                return
            salt, password_hash = _new_secret(password)
            now = _now()
            connection.execute(
                "INSERT INTO users(username,password_hash,salt,role,enabled,must_change_password,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                ("admin", password_hash, salt, "admin", 1, 1, now, now),
            )

    def _row(self, username: str):
        with self.meta.connect() as connection:
            row = connection.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if row is None:
            raise DomainError("USER_NOT_FOUND", "用户不存在", status_code=404)
        return row

    def authenticate(self, username: str, password: str) -> dict[str, object]:
        try:
            row = self._row(username)
        except DomainError as exc:
            raise DomainError("AUTH_FAILED", "用户名或密码错误", status_code=401) from exc
        if not int(row["enabled"]):
            raise DomainError("AUTH_FAILED", "用户名或密码错误", status_code=401)
        try:
            salt = bytes.fromhex(str(row["salt"]))
            actual = _derive(password, salt)
        except Exception as exc:
            raise DomainError("AUTH_FAILED", "用户名或密码错误", status_code=401) from exc
        if not hmac.compare_digest(actual, str(row["password_hash"])):
            raise DomainError("AUTH_FAILED", "用户名或密码错误", status_code=401)
        return self._public(dict(row))

    @staticmethod
    def _public(row: dict[str, object]) -> dict[str, object]:
        return {
            "username": row["username"],
            "role": row["role"],
            "enabled": bool(row["enabled"]),
            "must_change_password": bool(row["must_change_password"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def get(self, username: str) -> dict[str, object]:
        return self._public(dict(self._row(username)))

    def list(self) -> list[dict[str, object]]:
        with self.meta.connect() as connection:
            rows = connection.execute("SELECT * FROM users ORDER BY role,username").fetchall()
        return [self._public(dict(row)) for row in rows]

    def create(self, username: str, password: str, role: str) -> dict[str, object]:
        username = username.strip()
        if not username or len(username) > 80:
            raise DomainError("INVALID_USERNAME", "用户名不能为空且不能超过80个字符", status_code=422)
        self._validate_password(password)
        if role not in ROLES:
            raise DomainError("INVALID_ROLE", "用户角色不正确", status_code=422)
        salt, password_hash = _new_secret(password)
        now = _now()
        try:
            with self.meta.connect() as connection:
                connection.execute(
                    "INSERT INTO users(username,password_hash,salt,role,enabled,must_change_password,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                    (username, password_hash, salt, role, 1, 1, now, now),
                )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise DomainError("USER_ALREADY_EXISTS", "用户名已存在", status_code=409) from exc
            raise
        return self.get(username)

    @staticmethod
    def _validate_password(password: str) -> None:
        if len(password) < 10:
            raise DomainError("WEAK_PASSWORD", "密码至少需要10个字符", status_code=422)
        if not any(char.isalpha() for char in password) or not any(char.isdigit() for char in password):
            raise DomainError("WEAK_PASSWORD", "密码必须同时包含字母和数字", status_code=422)

    def set_password(self, username: str, password: str, *, must_change_password: bool = False) -> dict[str, object]:
        row = self._row(username)
        self._validate_password(password)
        try:
            same_as_current = hmac.compare_digest(
                _derive(password, bytes.fromhex(str(row["salt"]))),
                str(row["password_hash"]),
            )
        except Exception:
            same_as_current = False
        if same_as_current:
            raise DomainError("PASSWORD_REUSE", "新密码不能与当前密码相同", status_code=422)
        salt, password_hash = _new_secret(password)
        with self.meta.connect() as connection:
            connection.execute(
                "UPDATE users SET password_hash=?,salt=?,must_change_password=?,updated_at=? WHERE username=?",
                (password_hash, salt, 1 if must_change_password else 0, _now(), username),
            )
        return self.get(username)

    def update(self, username: str, *, role: str | None = None, enabled: bool | None = None) -> dict[str, object]:
        current = self.get(username)
        new_role = str(current["role"]) if role is None else role
        new_enabled = bool(current["enabled"]) if enabled is None else bool(enabled)
        if new_role not in ROLES:
            raise DomainError("INVALID_ROLE", "用户角色不正确", status_code=422)
        if current["role"] == "admin" and (new_role != "admin" or not new_enabled):
            with self.meta.connect() as connection:
                row = connection.execute("SELECT COUNT(*) AS count FROM users WHERE role='admin' AND enabled=1").fetchone()
            if int(row["count"]) <= 1:
                raise DomainError("LAST_ADMIN_REQUIRED", "系统至少需要保留一个启用的管理员", status_code=409)
        with self.meta.connect() as connection:
            connection.execute(
                "UPDATE users SET role=?,enabled=?,updated_at=? WHERE username=?",
                (new_role, 1 if new_enabled else 0, _now(), username),
            )
        return self.get(username)
