from __future__ import annotations

from dataclasses import dataclass
import secrets
import time


@dataclass(frozen=True)
class Session:
    token: str
    expires_at: float
    username: str
    role: str


class SessionStore:
    """Single-process authenticated session store.

    User/password/role state is persisted in SQLite. Session tokens remain
    process-local by design; a service restart invalidates browser sessions,
    which is safer than silently accepting stale authorization state.
    """

    def __init__(self, ttl_seconds: int) -> None:
        self.ttl_seconds = ttl_seconds
        self._sessions: dict[str, Session] = {}

    def create(self, username: str = "admin", role: str = "admin") -> Session:
        token = secrets.token_urlsafe(32)
        session = Session(
            token=token,
            expires_at=time.time() + self.ttl_seconds,
            username=username,
            role=role,
        )
        self._sessions[token] = session
        return session

    def get(self, token: str | None) -> Session | None:
        if not token:
            return None
        session = self._sessions.get(token)
        if session is None:
            return None
        if session.expires_at <= time.time():
            self._sessions.pop(token, None)
            return None
        return session

    def validate(self, token: str | None) -> bool:
        return self.get(token) is not None

    def revoke(self, token: str | None) -> None:
        if token:
            self._sessions.pop(token, None)

    def revoke_user(self, username: str) -> None:
        for token, session in list(self._sessions.items()):
            if session.username == username:
                self._sessions.pop(token, None)
