# -*- coding: utf-8 -*-
"""Thread-safe priority queue for Renamer metadata lookup jobs."""
from __future__ import annotations

from collections import deque
from threading import Condition
from typing import Iterable

from ..core.path_syntax import path_compare_key


class RenamerResolveJobQueue:
    """Allows GUI-side reprioritization/cancellation while the worker keeps running."""

    def __init__(self, jobs: Iterable[tuple] = ()) -> None:
        self._jobs = deque(jobs)
        self._condition = Condition()

    @staticmethod
    def _job_key(job: tuple) -> str:
        return path_compare_key(job[1]) if len(job) > 1 else ""

    def take(self, *, grace_seconds: float = 0.15) -> tuple | None:
        """Return the next job, briefly waiting for a late GUI priority request."""
        with self._condition:
            if not self._jobs:
                self._condition.wait(timeout=max(0.0, float(grace_seconds)))
            return self._jobs.popleft() if self._jobs else None

    def prepend(self, jobs: Iterable[tuple]) -> int:
        """Put jobs in front and drop older still-pending jobs for the same paths."""
        incoming = list(jobs)
        if not incoming:
            return 0
        keys = {self._job_key(job) for job in incoming if self._job_key(job)}
        with self._condition:
            if keys:
                self._jobs = deque(job for job in self._jobs if self._job_key(job) not in keys)
            for job in reversed(incoming):
                self._jobs.appendleft(job)
            self._condition.notify_all()
        return len(incoming)

    def cancel_paths(self, paths: Iterable[str]) -> int:
        """Remove jobs that have not started yet for the supplied source paths."""
        keys = {path_compare_key(path) for path in paths if str(path or "").strip()}
        if not keys:
            return 0
        with self._condition:
            before = len(self._jobs)
            self._jobs = deque(job for job in self._jobs if self._job_key(job) not in keys)
            return before - len(self._jobs)
