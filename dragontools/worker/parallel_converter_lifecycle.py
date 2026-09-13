from __future__ import annotations

import time
from pathlib import Path

from .cleanup_service import cleanup_empty_overwrite_dirs


class ParallelConverterLifecycleMixin:
    """Run lifecycle, aggregate progress, diagnostics and final cleanup."""

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._run_start_ts = time.time()
        worker_count = min(self.parallel_jobs, len(self._pending_files))
        self._logger.header(
            gpus=self._log_gpu_list,
            chosen_encoder=self._log_enc_name,
            total_files=len(self.files),
            codec=self.codec,
            crf=self.crf,
            preset=self.preset,
            scale_mode=self.scale_mode,
            overwrite_original=self.overwrite_original,
            strip_only=self.strip_only,
            encoder_options=self.encoder_options,
            manual_override_count=len(self.file_overrides),
        )
        self._logger.info(
            f"⚙️  Parallele Bearbeitung: {worker_count} Worker aktiv "
            f"(Limit: {self.parallel_jobs})."
        )
        if not self._pending_files:
            self._finish_if_done()
            return
        self._start_pending_workers()

    def isRunning(self) -> bool:
        return self._running

    def aggregate_progress_percent(self) -> int:
        return self._queue_state.aggregate_progress_percent()

    def active_file_count(self) -> int:
        return sum(1 for worker in self._active_workers if worker.isRunning())

    def display_position_for_path(
        self,
        path: str,
        *,
        fallback_idx: int,
        fallback_total: int,
    ) -> tuple[int, int]:
        return self._queue_state.display_position(path, fallback_idx, fallback_total)

    def diagnostic_snapshot(self) -> dict:
        return {
            "type": "parallel_converter",
            "running": bool(self._running),
            "paused": bool(self._paused),
            "abort_requested": bool(self.abort_requested),
            "abort_type": self.abort_type or "",
            "parallel_jobs": int(self.parallel_jobs),
            "active_count": int(self.active_file_count()),
            "postprocessing_count": int(len(self._postprocessing_workers)),
            "progress_percent": int(self.aggregate_progress_percent()),
            "total_files": len(self.files),
            "done_files": list(self._terminal_inputs),
            "pending_files": list(self._pending_files),
            "active_workers": self._registry.diagnostic_workers(),
            "file_progress": dict(self._file_progress_pct),
            "log_file": getattr(self, "log_file_path", "") or "",
        }

    def _finish_if_done(self) -> None:
        if self._active_workers or self._postprocessing_workers or self._postprocessing_inputs:
            return
        if self._pending_files and not self.abort_requested:
            return
        if not self.abort_requested and len(self._terminal_inputs) < len(self.files):
            return
        if not self._running:
            return
        self._sync_replace_service()
        self._cleanup_empty_temp_overwrite_dirs_after_run()
        self._running = False
        if not self.abort_requested:
            self.progress.emit(100)
        self.finished.emit()

    def _emit_aggregate_progress(self) -> None:
        self.progress.emit(self.aggregate_progress_percent())

    def _logger_error(self, message: str) -> None:
        error = getattr(self._logger, "error", None)
        if callable(error):
            error(message)
            return
        self.log_line.emit(message)
        info = getattr(self._logger, "info", None)
        if callable(info):
            info(message)

    def _sync_replace_service(self) -> None:
        self._registry.sync_replace_service()

    def _cleanup_empty_temp_overwrite_dirs_after_run(self) -> None:
        if not self.overwrite_original:
            return
        try:
            base_dirs = {Path(path).parent for path in self.files if str(path or "")}
            cleanup_empty_overwrite_dirs(
                base_dirs,
                temp_overwrite_dir=lambda base_dir: Path(base_dir) / "__temp_overwrite__",
                log=lambda msg, level="info": self._logger.warn(msg)
                if level == "warn"
                else self._logger.info(msg),
            )
        except Exception as exc:
            self._logger.warn(f"📝 Temporäre Overwrite-Ordner konnten nicht bereinigt werden: {exc}")
