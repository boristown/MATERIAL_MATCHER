from __future__ import annotations

import hmac
import secrets
import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Session:
    token: str
    expires_at: float


class SessionStore:
    def __init__(self, ttl_seconds: int = 8 * 60 * 60) -> None:
        self._ttl_seconds = ttl_seconds
        self._sessions: dict[str, float] = {}
        self._lock = threading.Lock()

    def create(self) -> Session:
        token = secrets.token_urlsafe(32)
        expires_at = time.time() + self._ttl_seconds
        with self._lock:
            self._sessions[token] = expires_at
            self._prune_locked()
        return Session(token=token, expires_at=expires_at)

    def validate(self, token: str) -> bool:
        now = time.time()
        with self._lock:
            expires_at = self._sessions.get(token)
            if expires_at is None:
                return False
            if expires_at <= now:
                self._sessions.pop(token, None)
                return False
            return True

    def revoke(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(token, None)

    def _prune_locked(self) -> None:
        now = time.time()
        expired = [token for token, expires_at in self._sessions.items() if expires_at <= now]
        for token in expired:
            self._sessions.pop(token, None)


def verify_admin_password(expected: str, supplied: str) -> bool:
    if not expected:
        return False
    return hmac.compare_digest(expected.encode("utf-8"), supplied.encode("utf-8"))
