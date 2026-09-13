from __future__ import annotations

import threading

_SEMAPHORE_LOCK = threading.Lock()
_SEMAPHORE_SIZE = 0
_SEMAPHORE: threading.Semaphore | None = None


class trickplay_semaphore:
    def __init__(self, max_jobs: int) -> None:
        self.max_jobs = max(1, int(max_jobs or 1))
        self._sem: threading.Semaphore | None = None

    def __enter__(self):
        global _SEMAPHORE, _SEMAPHORE_SIZE
        with _SEMAPHORE_LOCK:
            if _SEMAPHORE is None or _SEMAPHORE_SIZE != self.max_jobs:
                _SEMAPHORE = threading.Semaphore(self.max_jobs)
                _SEMAPHORE_SIZE = self.max_jobs
            self._sem = _SEMAPHORE
        self._sem.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._sem is not None:
            self._sem.release()
