from __future__ import annotations

from ..core.paths import display_name, path_compare_key
from .worker_contracts import RemoveFileStatus


class ParallelConverterQueueMixin:
    """Queue mutation and display ordering for the parallel converter."""

    def add_file(self, path: str) -> bool:
        if not self._running or self.abort_requested:
            return False
        key = path_compare_key(path)
        if key in self._assigned or key in {path_compare_key(p) for p in self.files}:
            return False

        active = [worker for worker in self._active_workers if worker.isRunning()]
        self.files.append(path)
        self._rebuild_display_positions()
        if len(active) < self.parallel_jobs:
            self._start_child_worker([path])
            self._logger.info(f"➕ Queue: {display_name(path)} als neuer Parallel-Worker hinzugefügt.")
            self._emit_aggregate_progress()
            return True

        self._pending_files.append(path)
        self._logger.info(f"➕ Queue: {display_name(path)} wartend hinzugefügt.")
        self._emit_aggregate_progress()
        return True

    def remove_file(self, path: str) -> RemoveFileStatus:
        key = path_compare_key(path)
        for index, pending_path in enumerate(list(self._pending_files)):
            if path_compare_key(pending_path) == key:
                del self._pending_files[index]
                self.files = [p for p in self.files if path_compare_key(p) != key]
                self._file_progress_pct.pop(path, None)
                self._rebuild_display_positions()
                self._logger.info(f"Queue: '{display_name(path)}' entfernt.")
                self._emit_aggregate_progress()
                return RemoveFileStatus.REMOVED

        worker = self._assigned.get(key)
        candidates = [worker] if worker is not None else list(self._workers)
        for candidate in candidates:
            if candidate is None:
                continue
            state = candidate.remove_file(path)
            if state != RemoveFileStatus.NOT_FOUND:
                if state == RemoveFileStatus.REMOVED:
                    self._assigned.pop(key, None)
                    self.files = [p for p in self.files if path_compare_key(p) != key]
                    self._file_progress_pct.pop(path, None)
                    self._rebuild_display_positions()
                self._emit_aggregate_progress()
                return state
        return RemoveFileStatus.NOT_FOUND

    def reorder_waiting_files(self, new_order: list[str]) -> None:
        order = list(new_order or [])
        self._queue_state.reorder(order)
        self._sync_child_display_positions()
        for worker in self._workers:
            worker.reorder_waiting_files(order)
        self._emit_aggregate_progress()

    def update_override(self, path: str, override: dict) -> bool:
        key = path_compare_key(path)
        worker = self._assigned.get(key)
        if worker is None:
            if key in {path_compare_key(p) for p in self._pending_files}:
                self.file_overrides[path] = dict(override or {})
                self._logger.info(f"🛠️ Override für '{display_name(path)}' gesetzt.")
                return True
            return False
        ok = worker.update_override(path, override)
        if ok:
            self.file_overrides[path] = dict(override or {})
        return ok

    def _rebuild_display_positions(self) -> None:
        self._queue_state.rebuild_display_positions()
        self._sync_child_display_positions()

    def _sync_child_display_positions(self) -> None:
        for worker in self._workers:
            worker._display_index_by_path = self._display_index_by_path
            worker._display_total = self._display_total

    def _start_pending_workers(self) -> None:
        while self._pending_files and len(self._active_workers) < self.parallel_jobs:
            path = self._pending_files.pop(0)
            self._start_child_worker([path])
