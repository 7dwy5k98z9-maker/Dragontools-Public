# -*- coding: utf-8 -*-
"""Persistence adapter for conversion job-journal file lifecycle events."""
from __future__ import annotations

from typing import Callable


class ConversionJobJournalTracker:
    def __init__(self, *, state, log: Callable) -> None:
        self._state = state
        self._log = log

    def mark_file_started(self, path: str) -> None:
        journal = getattr(self._state, "job_journal", None)
        if journal is None:
            return
        current_paths = getattr(self._state, "job_journal_current_paths", set())
        if path in current_paths:
            return
        try:
            done = len(self._state.completed_inputs)
            index = done + 1
            total = self._state.total_files
            thread = self._state.thread
            if thread and hasattr(thread, "display_position_for_path"):
                index, total = thread.display_position_for_path(
                    path,
                    fallback_idx=index,
                    fallback_total=total,
                )
            journal.start_file(path, index=index, total=total)
        except (OSError, RuntimeError, TypeError, ValueError, AttributeError) as exc:
            self._log(f"⚠️ Job-Journal konnte Dateistart nicht speichern: {exc}", "warn")
            return
        self._state.job_journal_current_path = path
        current_paths.add(path)
