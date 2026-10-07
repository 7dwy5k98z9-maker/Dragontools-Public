# -*- coding: utf-8 -*-
from __future__ import annotations

from ..core.callback_dispatch import invoke_callback
from .parallel_queue_coordination import coordinated_change, canonical_owned_input
from ..core.path_syntax import display_name, path_compare_key


class ParallelChildResultCoordinator:
    """Verarbeitet Child-Ergebnisse und hält Registry/Result-State konsistent."""

    def __init__(self, *, registry, queue_state, result_state) -> None:
        self._registry = registry
        self._queue = queue_state
        self._results = result_state

    @coordinated_change
    def on_encode_stage_complete(
        self,
        child,
        input_path: str,
        output_path: str,
        *,
        abort_requested: bool,
        start_pending_workers,
        emit_encode_stage_complete,
        emit_aggregate_progress,
        finish_if_done,
    ) -> None:
        input_path = canonical_owned_input(self._queue, child, input_path)
        if input_path is None or input_path in self._queue.dv_postprocessing_inputs:
            return
        self._queue.dv_postprocessing_inputs.add(input_path)
        self._queue.file_progress_pct[input_path] = 90
        if child in self._registry.active_workers:
            self._registry.active_workers.discard(child)
            self._registry.postprocessing_workers.add(child)
            if not abort_requested:
                invoke_callback(start_pending_workers)
        invoke_callback(emit_encode_stage_complete, input_path, output_path)
        invoke_callback(emit_aggregate_progress)
        invoke_callback(finish_if_done)

    @coordinated_change
    def on_file_result(
        self,
        child,
        input_path: str,
        output_path: str,
        status: str,
        *,
        abort_requested: bool,
        start_pending_workers,
        emit_file_result,
        emit_aggregate_progress,
        finish_if_done,
    ) -> None:
        original_path = input_path
        input_path = canonical_owned_input(self._queue, child, input_path)
        if input_path is None:
            return
        self._registry.sync_child_maps(child, original_path)
        if status == "🧩":
            # Terminal state is monotonic. Never resurrect a completed input
            # when a delayed pending event arrives from a very fast or legacy
            # child worker.
            if input_path in self._queue.terminal_inputs:
                invoke_callback(emit_aggregate_progress)
                invoke_callback(finish_if_done)
                return
            self._queue.postprocessing_inputs.add(input_path)
            if child in self._registry.active_workers:
                self._registry.active_workers.discard(child)
                self._registry.postprocessing_workers.add(child)
                if not abort_requested:
                    invoke_callback(start_pending_workers)
            invoke_callback(emit_file_result, input_path, output_path, status)
            invoke_callback(emit_aggregate_progress)
            invoke_callback(finish_if_done)
            return

        if status in {"✅", "❌", "⚠️", "⏭️"}:
            self._queue.postprocessing_inputs.discard(input_path)
            self._queue.dv_postprocessing_inputs.discard(input_path)
            self._queue.terminal_inputs.add(input_path)
            self._queue.file_progress_pct.pop(input_path, None)
        invoke_callback(emit_file_result, input_path, output_path, status)
        invoke_callback(emit_aggregate_progress)
        invoke_callback(finish_if_done)

    @coordinated_change
    def on_finished(
        self,
        child,
        *,
        abort_requested: bool,
        start_pending_workers,
        emit_file_result,
        emit_file_progress,
        logger_error,
        emit_aggregate_progress,
        finish_if_done,
    ) -> None:
        if child not in self._registry.workers or child in self._registry.finished_workers:
            return
        self._registry.finished_workers.add(child)
        self._registry.sync_child_maps(child)
        self.mark_unreported_files_failed(
            child,
            emit_file_result=emit_file_result,
            emit_file_progress=emit_file_progress,
            logger_error=logger_error,
        )
        self._registry.active_workers.discard(child)
        self._registry.postprocessing_workers.discard(child)
        if not abort_requested:
            invoke_callback(start_pending_workers)
        invoke_callback(emit_aggregate_progress)
        invoke_callback(finish_if_done)

    @coordinated_change
    def mark_unreported_files_failed(
        self,
        child,
        *,
        emit_file_result,
        emit_file_progress,
        logger_error,
    ) -> None:
        unreported = self._registry.unreported_child_files(child)
        if not unreported:
            return
        invoke_callback(
            logger_error,
            f"❌ Kritischer Fehler: Worker beendet ohne Dateiergebnis ({len(unreported)} Datei(en)).",
        )
        session = getattr(child, "_session_state", None)
        child_failures = getattr(session, "failure_details", None) if session is not None else None
        if not isinstance(child_failures, dict):
            child_failures = getattr(child, "_failure_details", {}) or {}
        child_failed_count = int(getattr(child, "fehlgeschlagen", 0) or 0)
        for path in unreported:
            self._registry.sync_child_maps(child, path)
            details = dict(child_failures.get(path, {}) or {}) or {
                "message": "Worker beendet ohne finales Dateiergebnis.",
                "error_report": "",
                "pipeline": "",
                "container": "",
                "strategy": "parallel_worker_finished",
            }
            self._results.failure_details[path] = details
            self._queue.terminal_inputs.add(path)
            self._queue.postprocessing_inputs.discard(path)
            self._queue.dv_postprocessing_inputs.discard(path)
            self._queue.file_progress_pct.pop(path, None)
            self._queue.assigned.pop(path_compare_key(path), None)
            if child_failed_count <= 0:
                self._results.synthetic_failures += 1
            invoke_callback(emit_file_result, path, path, "❌")
            invoke_callback(emit_file_progress, path, 100, None)
            invoke_callback(logger_error, f"Fehler: {display_name(path)}")
            if details.get("message"):
                invoke_callback(logger_error, str(details["message"]))
