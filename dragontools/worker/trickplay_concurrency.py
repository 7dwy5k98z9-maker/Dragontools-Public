from __future__ import annotations

import threading
from pathlib import Path

_LIMIT_CONDITION = threading.Condition()
_ACTIVE_JOBS = 0
_ACTIVE_LIMIT = 0

_TARGET_LOCKS_GUARD = threading.Lock()
_TARGET_LOCKS: dict[str, tuple[threading.Lock, int]] = {}


class trickplay_semaphore:
    def __init__(self, max_jobs: int, *, abort_check=None) -> None:
        self.max_jobs = max(1, int(max_jobs or 1))
        self._entered = False
        self.abort_check = abort_check

    def __enter__(self):
        global _ACTIVE_JOBS, _ACTIVE_LIMIT
        with _LIMIT_CONDITION:
            while True:
                if self.abort_check is not None and self.abort_check():
                    raise RuntimeError('Trickplay abgebrochen.')
                if _ACTIVE_JOBS == 0:
                    _ACTIVE_LIMIT = self.max_jobs
                else:
                    # A live settings change must never replace the semaphore
                    # object while old jobs still hold permits.  Tightening the
                    # limit is applied immediately/conservatively; increasing it
                    # takes effect naturally once the current generation drains.
                    _ACTIVE_LIMIT = min(max(1, _ACTIVE_LIMIT), self.max_jobs)
                if _ACTIVE_JOBS < max(1, _ACTIVE_LIMIT):
                    _ACTIVE_JOBS += 1
                    self._entered = True
                    break
                _LIMIT_CONDITION.wait(timeout=0.1)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        global _ACTIVE_JOBS, _ACTIVE_LIMIT
        if not self._entered:
            return
        with _LIMIT_CONDITION:
            _ACTIVE_JOBS = max(0, _ACTIVE_JOBS - 1)
            if _ACTIVE_JOBS == 0:
                _ACTIVE_LIMIT = 0
            self._entered = False
            _LIMIT_CONDITION.notify_all()


class trickplay_target_lock:
    """Serialize writes to one ``*.trickplay`` root inside this process.

    Different media items may still run concurrently.  Jobs targeting the same
    final root cannot share/delete the fixed partial directory concurrently.
    """

    def __init__(self, target_root: str | Path, *, abort_check=None) -> None:
        self.key = str(Path(target_root).resolve()).casefold()
        self._lock: threading.Lock | None = None
        self.abort_check = abort_check

    def __enter__(self):
        with _TARGET_LOCKS_GUARD:
            lock, refs = _TARGET_LOCKS.get(self.key, (threading.Lock(), 0))
            _TARGET_LOCKS[self.key] = (lock, refs + 1)
            self._lock = lock
        try:
            while not self._lock.acquire(timeout=0.1):
                if self.abort_check is not None and self.abort_check():
                    raise RuntimeError('Trickplay abgebrochen.')
        except BaseException:
            self._retire()
            raise
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        lock = self._lock
        if lock is None:
            return
        lock.release()
        self._retire()

    def _retire(self):
        lock = self._lock
        with _TARGET_LOCKS_GUARD:
            current = _TARGET_LOCKS.get(self.key)
            if current is not None and current[0] is lock:
                refs = current[1] - 1
                if refs <= 0:
                    _TARGET_LOCKS.pop(self.key, None)
                else:
                    _TARGET_LOCKS[self.key] = (lock, refs)
        self._lock = None


def reset_trickplay_concurrency_for_tests() -> None:
    global _ACTIVE_JOBS, _ACTIVE_LIMIT
    with _LIMIT_CONDITION:
        _ACTIVE_JOBS = 0
        _ACTIVE_LIMIT = 0
        _LIMIT_CONDITION.notify_all()
    with _TARGET_LOCKS_GUARD:
        _TARGET_LOCKS.clear()
