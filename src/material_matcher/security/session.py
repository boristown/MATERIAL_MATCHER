from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import secrets
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from material_matcher.storage.metadata import MetadataRepository


@dataclass(frozen=True)
class Session:
    token: str
    expires_at: float
    username: str
    role: str


class SessionStore:
    """SQLite-backed session store.

    会话持久化以支持长周期登录(内网部署诉求):服务重启不再清空浏览器会话,
    TTL 由 MATERIAL_MATCHER_SESSION_TTL_SECONDS 配置。授权状态不依赖会话缓存——
    中间件每次请求都从 users 表核对 enabled/role,改角色、停用、重置密码仍会
    立即吊销会话(revoke_user),安全语义与原内存版一致。
    """

    def __init__(self, metadata: "MetadataRepository", ttl_seconds: int) -> None:
        self.meta = metadata
        self.ttl_seconds = max(60, int(ttl_seconds))

    def create(self, username: str = "admin", role: str = "admin") -> Session:
        token = secrets.token_urlsafe(32)
        now = time.time()
        session = Session(token=token, expires_at=now + self.ttl_seconds, username=username, role=role)
        with self.meta.connect() as connection:
            connection.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
            connection.execute(
                "INSERT INTO sessions(token,username,role,expires_at,created_at) VALUES(?,?,?,?,?)",
                (token, username, role, session.expires_at, datetime.now().astimezone().isoformat()),
            )
        return session

    def get(self, token: str | None) -> Session | None:
        if not token:
            return None
        with self.meta.connect() as connection:
            row = connection.execute("SELECT * FROM sessions WHERE token=?", (token,)).fetchone()
            if row is None:
                return None
            if float(row["expires_at"]) <= time.time():
                connection.execute("DELETE FROM sessions WHERE token=?", (token,))
                return None
            return Session(token=str(row["token"]), expires_at=float(row["expires_at"]), username=str(row["username"]), role=str(row["role"]))

    def validate(self, token: str | None) -> bool:
        return self.get(token) is not None

    def revoke(self, token: str | None) -> None:
        if token:
            with self.meta.connect() as connection:
                connection.execute("DELETE FROM sessions WHERE token=?", (token,))

    def revoke_user(self, username: str) -> None:
        with self.meta.connect() as connection:
            connection.execute("DELETE FROM sessions WHERE username=?", (username,))
