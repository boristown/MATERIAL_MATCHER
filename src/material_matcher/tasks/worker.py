from __future__ import annotations

import logging
import threading

from material_matcher.services.match_service import MatchService

logger = logging.getLogger("material_matcher.worker")


class TaskWorker:
    """Single-node persistent SQLite-backed task worker.

    PENDING/RECOVERING rows live in SQLite, so a service restart does not lose the
    queue. This intentionally remains single-node for the first offline deployment.
    """

    def __init__(self, service: MatchService, poll_seconds: float = 0.5) -> None:
        self.service = service
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="material-matcher-worker", daemon=True)
        self._thread.start()

    def notify(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop.set(); self._wake.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            task_id = self.service.claim_next_task()
            if task_id:
                try:
                    self.service.execute_task(task_id)
                except Exception:
                    logger.exception("task execution crashed task_id=%s", task_id)
                continue
            self._wake.wait(self.poll_seconds)
            self._wake.clear()
