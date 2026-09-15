"""Job-local process slot with inherited batch cancellation/pause signals."""
from __future__ import annotations

import threading


class JobProcessOwner:
    """Never forwards the parent's process slot/lock to a background job."""

    def __init__(self, parent):
        self.parent = parent
        self._lock = threading.Lock()
        self._current_process = None
        self._cancelled = threading.Event()

    @property
    def abort_requested(self):
        return self._cancelled.is_set() or bool(getattr(self.parent, "abort_requested", False))

    @property
    def abort_type(self):
        return "sofort" if self._cancelled.is_set() else getattr(self.parent, "abort_type", None)

    @property
    def _paused(self):
        return not self.abort_requested and bool(getattr(self.parent, "_paused", False))

    @property
    def _pause_ev(self):
        return getattr(self.parent, "_pause_ev", None)

    def request_abort(self, mode="sofort"):
        # Job-local cancellation; no mutation of sibling/parent control flags.
        self._cancelled.set()

    def log(self, message, level="info"):
        from .log_dispatch import dispatch_log
        dispatch_log(getattr(self.parent, "log", None), message, level)
