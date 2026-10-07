from __future__ import annotations

from ..core.parallel_settings import clamp_parallel_jobs
from .parallel_child_controls import apply_child_control
from .parallel_queue_coordination import coordinated_change
from .parallel_file_control import individually_paused_workers

class ParallelConverterControlMixin:
    """Pause, abort and per-child runtime controls."""

    @coordinated_change
    def set_parallel_jobs(self, jobs: int) -> int:
        """Change the encode limit on the coordinator's Qt thread.

        A reduction drains running children without interrupting a file.
        An increase immediately fills free slots from the central queue.
        """
        previous = self.parallel_jobs
        self.parallel_jobs = clamp_parallel_jobs(jobs, previous)
        if self.parallel_jobs == previous:
            return self.parallel_jobs
        self._logger.info(
            f"⚙️ Worker-Limit: {previous} → {self.parallel_jobs}. "
            "Laufende Dateien werden vollständig verarbeitet."
        )
        if self._running and not self.abort_requested and not self._paused:
            self._start_pending_workers()
        self._emit_aggregate_progress()
        return self.parallel_jobs

    @coordinated_change
    def pause(self) -> None:
        self._paused = True
        apply_child_control(self._workers, "pause", log=self._logger)

    @coordinated_change
    def resume(self) -> None:
        self._paused = False
        paused_children = individually_paused_workers(getattr(self, "_queue_state", None))
        apply_child_control([child for child in self._workers if child not in paused_children], "resume", log=self._logger)
        if self._running and not self.abort_requested:
            self._start_pending_workers()

    @coordinated_change
    def request_abort(self, mode: str = "sofort") -> None:
        self.abort_requested = True
        self.abort_type = mode
        state = getattr(self, "_queue_state", None)
        apply_child_control(individually_paused_workers(state), "resume", log=self._logger)
        if state is not None:
            state.individually_paused.clear()
        if self._paused:
            self.resume()
        apply_child_control(self._workers, "request_abort", mode, log=self._logger)
        self._finish_if_done()

    def is_current(self, path: str) -> bool:
        # A DV child remains logically current while metadata injection/final mux
        # continues after its encode slot was released. Keep queue mutation guards
        # active for both encoder and postprocessing workers.
        workers = list(self._active_workers | self._postprocessing_workers)
        return any(
            worker.isRunning() and hasattr(worker, "is_current") and worker.is_current(path)
            for worker in workers
        )

    def terminate_current_ffmpeg(self, path: str | None = None) -> bool:
        # Per-file termination must also reach FFmpeg used by DV/HDR10+
        # postprocessing after the encode slot has already been released.
        for worker in list(self._active_workers | self._postprocessing_workers):
            if not worker.isRunning():
                continue
            if path and hasattr(worker, "is_current") and not worker.is_current(path):
                continue
            if hasattr(worker, "terminate_current_ffmpeg") and worker.terminate_current_ffmpeg(path):
                return True
        return False

    @coordinated_change
    def clear_abort_request(self) -> bool:
        if not self.abort_requested or self.abort_type != "nach_datei":
            return False
        self.abort_requested = False
        self.abort_type = None
        for worker in self._workers:
            if getattr(worker, "abort_type", None) != "nach_datei":
                continue
            clear_child_abort = getattr(worker, "clear_abort_request", None)
            if callable(clear_child_abort):
                clear_child_abort()
                continue
            # Compatibility fallback for simple/legacy workers that expose
            # mutable abort attributes instead of the ConverterThread API.
            try:
                worker.abort_requested = False
                worker.abort_type = None
            except (AttributeError, RuntimeError, TypeError):
                self._logger.warn(
                    "⚠️ Abbruchstatus eines Child-Workers konnte nicht zurückgenommen werden."
                )
        self._logger.info("↩️ Abbruch nach Datei zurückgenommen.")
        if self._running:
            self._start_pending_workers()
            self._emit_aggregate_progress()
            self._finish_if_done()
        return True

    def cancel(self) -> None:
        self.request_abort()

    def _relay_dv_crop_decision(self, payload: object) -> None:
        self.dv_crop_decision_requested.emit(dict(payload or {}) if isinstance(payload, dict) else {})

    def provide_dv_crop_decision(self, request_id: str, decision: str) -> bool:
        return any(
            bool(getattr(worker, "provide_dv_crop_decision", lambda *_: False)(request_id, decision))
            for worker in list(self._workers)
        )
