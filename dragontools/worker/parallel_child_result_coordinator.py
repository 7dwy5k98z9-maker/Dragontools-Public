# -*- coding: utf-8 -*-
from __future__ import annotations

from ..core.paths import display_name, path_compare_key


class ParallelChildResultCoordinator:
    """Verarbeitet Child-Ergebnisse und hält Registry/Result-State konsistent."""

    def __init__(self, *, registry, queue_state, result_state) -> None:
        self._registry = registry
        self._queue = queue_state
        self._results = result_state

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
        self._registry.sync_child_maps(child, input_path)
        if status == "🧩":
            self._queue.postprocessing_inputs.add(input_path)
            if child in self._registry.active_workers:
                self._registry.active_workers.discard(child)
                self._registry.postprocessing_workers.add(child)
                if not abort_requested:
                    start_pending_workers()
            emit_file_result(input_path, output_path, status)
            emit_aggregate_progress()
            finish_if_done()
            return

        if status in {"✅", "❌", "⚠️", "⏭️"}:
            self._queue.postprocessing_inputs.discard(input_path)
            self._queue.terminal_inputs.add(input_path)
            self._queue.file_progress_pct.pop(input_path, None)
        emit_file_result(input_path, output_path, status)
        emit_aggregate_progress()
        finish_if_done()

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
            start_pending_workers()
        emit_aggregate_progress()
        finish_if_done()

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
        logger_error(
            f"❌ Kritischer Fehler: Worker beendet ohne Dateiergebnis ({len(unreported)} Datei(en))."
        )
        child_failures = getattr(child, "_failure_details", {}) or {}
        child_failed_count = int(getattr(child, "fehlgeschlagen", 0) or 0)
        for path in unreported:
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
            self._queue.file_progress_pct.pop(path, None)
            self._queue.assigned.pop(path_compare_key(path), None)
            if child_failed_count <= 0:
                self._results.synthetic_failures += 1
            emit_file_result(path, path, "❌")
            emit_file_progress(path, 100, None)
            logger_error(f"Fehler: {display_name(path)}")
            if details.get("message"):
                logger_error(str(details["message"]))
