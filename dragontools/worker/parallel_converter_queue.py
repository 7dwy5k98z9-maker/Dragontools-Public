from __future__ import annotations

from ..core.path_syntax import display_name, path_compare_key
from .worker_contracts import RemoveFileStatus
from .log_dispatch import dispatch_log
from .live_queue_overrides import override_key, set_file_override
from .parallel_queue_coordination import coordinated_change
from .parallel_launch_ownership import child_may_be_running


class ParallelConverterQueueMixin:
    """Queue mutation and display ordering for the parallel converter."""

    @coordinated_change
    def add_file_with_override(self, path: str, override: dict) -> bool:
        """Install per-file options before a free parallel slot can start the child worker."""
        if not self.accepts_live_file(path):
            return False
        key = override_key(self.file_overrides, path)
        missing = object()
        previous = self.file_overrides.get(key, missing)
        set_file_override(self.file_overrides, path, override)
        ok = self.add_file(path)
        if not ok:
            if previous is missing:
                self.file_overrides.pop(key, None)
            else:
                self.file_overrides[key] = previous
        return ok

    @coordinated_change
    def accepts_live_file(self, path: str) -> bool:
        key = path_compare_key(path)
        # An explicitly removed row may still belong to a child doing final
        # cleanup. Release its old ownership only after the native thread stops.
        owner = self._assigned.get(key)
        if (key not in self._queue_state.file_keys and owner is not None
                and not child_may_be_running(owner)):
            self._assigned.pop(key, None)
        return bool(self._running and not self.abort_requested
                    and key not in self._assigned and key not in self._queue_state.file_keys)

    @coordinated_change
    def add_file(self, path: str) -> bool:
        key = path_compare_key(path)
        if not self.accepts_live_file(path):
            return False

        active = [worker for worker in self._active_workers if worker.isRunning()]
        self.files.append(path)
        self._rebuild_display_positions()
        if len(active) < self.parallel_jobs and not self._paused:
            try:
                self._start_child_worker([path])
            except Exception as exc:
                # Live-add is all-or-nothing.  A failed child start must not
                # leave a phantom queue row or ownership marker behind.
                self.files = [p for p in self.files if path_compare_key(p) != key]
                self._rebuild_display_positions()
                dispatch_log(self._logger,
                    f"❌ Queue: Worker für {display_name(path)} konnte nicht gestartet werden: {exc}", "error"
                )
                return False
            dispatch_log(self._logger, f"➕ Queue: {display_name(path)} als neuer Parallel-Worker hinzugefügt.")
            self._emit_aggregate_progress()
            return True

        self._pending_files.append(path)
        dispatch_log(self._logger, f"➕ Queue: {display_name(path)} wartend hinzugefügt.")
        self._emit_aggregate_progress()
        return True

    @coordinated_change
    def remove_file(self, path: str) -> RemoveFileStatus:
        key = path_compare_key(path)
        for index, pending_path in enumerate(list(self._pending_files)):
            if path_compare_key(pending_path) == key:
                del self._pending_files[index]
                self._forget_removed_file(path)
                dispatch_log(self._logger, f"Queue: '{display_name(path)}' entfernt.")
                self._emit_aggregate_progress()
                return RemoveFileStatus.REMOVED

        worker = self._assigned.get(key)
        terminal = any(path_compare_key(p) == key for p in self._terminal_inputs)
        if terminal or (worker is not None and not child_may_be_running(worker)):
            self._forget_removed_file(path, release_owner=worker is None or not child_may_be_running(worker))
            self._emit_aggregate_progress()
            return RemoveFileStatus.REMOVED
        candidates = [worker] if worker is not None else list(self._workers)
        for candidate in candidates:
            if candidate is None:
                continue
            state = candidate.remove_file(path)
            if state != RemoveFileStatus.NOT_FOUND:
                if state == RemoveFileStatus.REMOVED:
                    self._forget_removed_file(path)
                self._emit_aggregate_progress()
                return state
        return RemoveFileStatus.NOT_FOUND

    def _forget_removed_file(self, path: str, *, release_owner: bool = True) -> None:
        """Forget one removed row without allowing old children to own a retry."""
        key = path_compare_key(path)
        if release_owner:
            self._assigned.pop(key, None)
        self.files = [p for p in self.files if path_compare_key(p) != key]
        self._queue_state.individually_paused.discard(key)
        for values in (self._terminal_inputs, self._postprocessing_inputs,
                       self._queue_state.dv_postprocessing_inputs):
            values.difference_update(p for p in list(values) if path_compare_key(p) == key)
        for p in list(self._file_progress_pct):
            if path_compare_key(p) == key:
                self._file_progress_pct.pop(p, None)
        results = getattr(self, '_result_state', None)
        if results is not None:
            for mapping in (results.sidecar_outputs, results.postprocess_outputs, results.failure_details):
                for p in list(mapping):
                    if path_compare_key(p) == key:
                        mapping.pop(p, None)
        self._rebuild_display_positions()

    @coordinated_change
    def reorder_waiting_files(self, new_order: list[str]) -> None:
        order = list(new_order or [])
        self._queue_state.reorder(order)
        self._sync_child_display_positions()
        for worker in self._workers:
            # Only the coordinator assigns files; sorting is not assignment.
            owned_order = [
                path for path in order
                if self._assigned.get(path_compare_key(path)) is worker
            ]
            worker.reorder_waiting_files(owned_order)
        self._emit_aggregate_progress()

    @coordinated_change
    def update_override(self, path: str, override: dict) -> bool:
        key = path_compare_key(path)
        worker = self._assigned.get(key)
        if worker is None:
            if key in {path_compare_key(p) for p in self._pending_files}:
                set_file_override(self.file_overrides, path, override)
                dispatch_log(self._logger, f"🛠️ Override für '{display_name(path)}' gesetzt.")
                return True
            return False
        ok = worker.update_override(path, override)
        if ok:
            set_file_override(self.file_overrides, path, override)
        return ok

    def _rebuild_display_positions(self) -> None:
        self._queue_state.rebuild_display_positions()
        self._sync_child_display_positions()

    def _sync_child_display_positions(self) -> None:
        for worker in self._workers:
            worker._display_index_by_path = self._display_index_by_path
            worker._display_total = self._display_total

    @coordinated_change
    def _start_pending_workers(self) -> None:
        if (not self._running or self.abort_requested or self._paused
                or getattr(self, "_launching_pending", False)):
            return
        self._launching_pending = True
        try:
            self._drain_pending_workers()
        finally:
            self._launching_pending = False
        finish = getattr(self, "_finish_if_done", None)
        if callable(finish):
            finish()

    def _drain_pending_workers(self) -> None:
        while (self._pending_files and len(self._active_workers) < self.parallel_jobs
                and self._running and not self.abort_requested and not self._paused):
            # Remove the waiting entry before start(): a synchronous completion
            # may reenter the coordinator and must never launch this row again.
            path = self._pending_files.pop(0)
            key = path_compare_key(path)
            if key in self._assigned:
                dispatch_log(self._logger,
                    f"⚠️ Doppelter Queue-Eintrag blockiert: {display_name(path)} ist bereits einem Worker zugeordnet.", "warn"
                )
                continue
            try:
                self._start_child_worker([path])
            except Exception as exc:
                self._terminal_inputs.add(path)
                self._result_state.failure_details[path] = {
                    "message": f"Parallel-Worker konnte nicht gestartet werden: {exc}",
                    "error_report": "", "pipeline": "", "container": "",
                    "strategy": "parallel_worker_start",
                }
                self._synthetic_failures += 1
                dispatch_log(self._logger,
                    f"❌ Queue: Worker für {display_name(path)} konnte nicht gestartet werden: {exc}", "error"
                )
                self.file_result.emit(path, path, "❌")
