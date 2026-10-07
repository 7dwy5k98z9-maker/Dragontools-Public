"""Exactly-once file statistics, shared by all worker completion paths."""
import threading

from .worker_contracts import normalize_worker_path


class WorkerResultAccounting:
    def __init__(self, runtime_state):
        self.lock = threading.RLock()
        self._runtime = runtime_state
        self._successes = {}
        self._failures = set()

    def recorded(self, path: str) -> bool:
        key = normalize_worker_path(path)
        with self.lock:
            return key in self._successes or key in self._failures

    def success(self, path: str, before: int, after: int) -> bool:
        key = normalize_worker_path(path)
        with self.lock:
            if key in self._successes or key in self._failures:
                return False
            self._successes[key] = (before, after)
            self._runtime.total_before += before
            self._runtime.total_after += after
            self._runtime.erfolgreich += 1
            return True

    def failure(self, path: str) -> bool:
        key = normalize_worker_path(path)
        with self.lock:
            if key in self._failures:
                return False
            self._failures.add(key)
            previous = self._successes.pop(key, None)
            if previous is not None:
                self._runtime.total_before -= previous[0]
                self._runtime.total_after -= previous[1]
                self._runtime.erfolgreich -= 1
            self._runtime.fehlgeschlagen += 1
            return True
