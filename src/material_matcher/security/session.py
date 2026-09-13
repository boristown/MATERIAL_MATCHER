from __future__ import annotations

from dataclasses import dataclass
import secrets
import time


@dataclass(frozen=True)
class Session:
    token: str
    expires_at: float


class SessionStore:
    """Single-process session store for the first deployable slice.

    Authentication is intentionally isolated behind this class so a persistent
    session backend can be introduced without changing API/domain code.
    """

    def __init__(self, ttl_seconds: int) -> None:
        self.ttl_seconds = ttl_seconds
        self._sessions: dict[str, float] = {}

    def create(self) -> Session:
        token = secrets.token_urlsafe(32)
        expires_at = time.time() + self.ttl_seconds
        self._sessions[token] = expires_at
        return Session(token=token, expires_at=expires_at)

    def validate(self, token: str | None) -> bool:
        if not token:
            return False
        expires_at = self._sessions.get(token, 0.0)
        if expires_at <= time.time():
            self._sessions.pop(token, None)
            return False
        return True

    def revoke(self, token: str | None) -> None:
        if token:
            self._sessions.pop(token, None)
