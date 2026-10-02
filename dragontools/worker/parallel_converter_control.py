from __future__ import annotations

from ..core.parallel_settings import clamp_parallel_jobs

class ParallelConverterControlMixin:
    """Pause, abort and per-child runtime controls."""

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

    def pause(self) -> None:
        self._paused = True
        for worker in self._workers:
            if worker.isRunning():
                worker.pause()

    def resume(self) -> None:
        self._paused = False
        for worker in self._workers:
            if worker.isRunning():
                worker.resume()
        if self._running and not self.abort_requested:
            self._start_pending_workers()

    def request_abort(self, mode: str = "sofort") -> None:
        self.abort_requested = True
        self.abort_type = mode
        if self._paused:
            self.resume()
        for worker in self._workers:
            if worker.isRunning():
                worker.request_abort(mode)

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

    def clear_abort_request(self) -> bool:
        if not self.abort_requested or self.abort_type != "nach_datei":
            return False
        self.abort_requested = False
        self.abort_type = None
        for worker in self._workers:
            if getattr(worker, "abort_type", None) == "nach_datei":
                worker.abort_requested = False
                worker.abort_type = None
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
