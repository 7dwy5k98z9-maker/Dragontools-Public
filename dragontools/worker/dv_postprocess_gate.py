# -*- coding: utf-8 -*-
"""Shared concurrency gate for heavy DV/HDR post-processing stages."""
from __future__ import annotations

import threading
from collections.abc import Callable


class DVPostprocessGate:
    def __init__(self, limit: int = 4) -> None:
        self.limit = max(1, int(limit))
        self._semaphore = threading.BoundedSemaphore(self.limit)
        self._lock = threading.Lock()
        self._active = 0

    @property
    def active(self) -> int:
        with self._lock:
            return self._active

    def acquire(self, *, abort_requested: Callable[[], bool] | None = None) -> bool:
        while True:
            if abort_requested is not None and abort_requested():
                return False
            if self._semaphore.acquire(timeout=0.2):
                with self._lock:
                    self._active += 1
                return True

    def release(self) -> None:
        with self._lock:
            if self._active <= 0:
                return
            self._active -= 1
        self._semaphore.release()


__all__ = ["DVPostprocessGate"]
