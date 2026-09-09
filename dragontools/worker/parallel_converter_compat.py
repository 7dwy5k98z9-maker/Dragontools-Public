# -*- coding: utf-8 -*-
from __future__ import annotations


class ParallelConverterCompatibilityMixin:
    """Dünne Zustands-/Metrikfassade für bestehende interne Aufrufer und Tests."""

    @property
    def files(self) -> list[str]:
        return self._queue_state.files

    @files.setter
    def files(self, value: list[str]) -> None:
        self._queue_state.files = list(value)

    @property
    def _workers(self):
        return self._registry.workers

    @property
    def _active_workers(self):
        return self._registry.active_workers

    @property
    def _postprocessing_workers(self):
        return self._registry.postprocessing_workers

    @property
    def _replace_service(self):
        return self._replace_service_summary

    @property
    def _pending_files(self):
        return self._queue_state.pending_files

    @_pending_files.setter
    def _pending_files(self, value):
        self._queue_state.pending_files = list(value)

    @property
    def _assigned(self):
        return self._queue_state.assigned

    @property
    def _file_progress_pct(self):
        return self._queue_state.file_progress_pct

    @property
    def _terminal_inputs(self):
        return self._queue_state.terminal_inputs

    @property
    def _postprocessing_inputs(self):
        return self._queue_state.postprocessing_inputs

    @property
    def _display_index_by_path(self):
        return self._queue_state.display_index_by_path

    @property
    def _display_total(self):
        return self._queue_state.display_total

    @property
    def _sidecar_outputs(self):
        return self._result_state.sidecar_outputs

    @property
    def _postprocess_outputs(self):
        return self._result_state.postprocess_outputs

    @property
    def _failure_details(self):
        return self._result_state.failure_details

    @property
    def _synthetic_failures(self):
        return self._result_state.synthetic_failures

    @_synthetic_failures.setter
    def _synthetic_failures(self, value):
        self._result_state.synthetic_failures = int(value)

    @property
    def total_before(self) -> int:
        return sum(int(getattr(worker, "total_before", 0) or 0) for worker in self._workers)

    @property
    def total_after(self) -> int:
        return sum(int(getattr(worker, "total_after", 0) or 0) for worker in self._workers)

    @property
    def erfolgreich(self) -> int:
        return sum(int(getattr(worker, "erfolgreich", 0) or 0) for worker in self._workers)

    @property
    def fehlgeschlagen(self) -> int:
        return (
            sum(int(getattr(worker, "fehlgeschlagen", 0) or 0) for worker in self._workers)
            + int(self._synthetic_failures)
        )
