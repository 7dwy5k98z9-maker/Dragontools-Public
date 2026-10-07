"""Synchronize scanner observations with GUI acknowledgements without locking I/O."""
from threading import RLock


def file_signature(stat):
    return ":".join(str(int(getattr(stat, name, 0))) for name in (
        "st_size", "st_mtime_ns", "st_dev", "st_ino", "st_ctime_ns",
    ))


class WatchObservationState:
    def __init__(self, processed=None):
        self._lock = RLock()
        self._processed = dict(processed or {})
        self._observations = {}

    def ready(self, key, signature, stamp, stable_seconds):
        with self._lock:
            if self._processed.get(key) == signature:
                self._observations.pop(key, None)
                return False
            observation = self._observations.get(key)
            if observation is None or observation[0] != signature:
                observation = (signature, stamp)
                self._observations[key] = observation
            return stamp - observation[1] >= stable_seconds

    def prune(self, seen):
        with self._lock:
            self._observations = {key: value for key, value in self._observations.items() if key in seen}

    def acknowledge(self, key, signature):
        with self._lock:
            self._processed[key] = signature
            self._observations.pop(key, None)

    def processed(self):
        with self._lock:
            return dict(self._processed)
