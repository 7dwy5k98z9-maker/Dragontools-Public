# -*- coding: utf-8 -*-
from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

from PyQt6.QtCore import QObject, QSettings, pyqtSignal

from ..core.logger import create_worker_logger
from ..core.parallel_settings import clamp_parallel_jobs
from ..core.paths import display_name, path_compare_key
from ..core.settings import APP_NAME, APP_ORG
from .worker_contracts import RemoveFileStatus
from .cleanup_service import cleanup_empty_overwrite_dirs
from .converter_config import ConverterConfig
from .converter_thread import ConverterThread
from .parallel_converter_state import ParallelQueueState, ParallelResultState, ParallelWorkerRegistry
from .parallel_converter_compat import ParallelConverterCompatibilityMixin
from .parallel_worker_launcher import ParallelWorkerLauncher
from .parallel_child_result_coordinator import ParallelChildResultCoordinator


class ParallelConverterThread(ParallelConverterCompatibilityMixin, QObject):
    """Koordiniert mehrere normale ConverterThread-Instanzen als einen Lauf."""

    progress = pyqtSignal(int)
    file_progress = pyqtSignal(str, int, object)
    file_result = pyqtSignal(str, str, str)
    log_line = pyqtSignal(str)
    event = pyqtSignal(object)
    dv_crop_decision_requested = pyqtSignal(object)
    finished = pyqtSignal()

    def __init__(
        self,
        files,
        config: ConverterConfig,
        *,
        parallel_jobs: int,
        parent=None,
    ) -> None:
        super().__init__(parent)
        if not isinstance(config, ConverterConfig):
            raise TypeError("config muss eine ConverterConfig-Instanz sein.")
        self.config = config
        self._queue_state = ParallelQueueState(list(files))
        self._result_state = ParallelResultState()
        self.codec = config.codec
        self.crf = config.crf
        self.preset = config.preset
        self.scale_mode = config.scale_mode
        self.overwrite_original = config.overwrite_original
        self.strip_only = config.strip_only
        self.encoder_options = dict(config.encoder_options or {})
        self.file_overrides = dict(config.file_overrides or {})
        self.subtitle_rules = dict(config.subtitle_rules or {})
        self.tv_path = config.tv_path
        self.anime_path = config.anime_path
        self.filme_path = config.filme_path
        self.parallel_jobs = clamp_parallel_jobs(parallel_jobs, 1)

        self.abort_requested = False
        self.abort_type = None
        self._paused = False
        self._running = False
        self._replace_service_summary = SimpleNamespace(blocked_move_inputs=set(), archiviert=0)
        self._registry = ParallelWorkerRegistry(
            self._queue_state, self._result_state, replace_service=self._replace_service_summary
        )
        self._child_results = ParallelChildResultCoordinator(
            registry=self._registry, queue_state=self._queue_state, result_state=self._result_state
        )

        self._logger = create_worker_logger(
            settings=QSettings(APP_ORG, APP_NAME),
            gui_callback=self.log_line.emit,
        )
        self.log_file_path = str(self._logger.log_file) if self._logger.log_file else None
        self._run_start_ts: float | None = None

        try:
            from ..core.gpu_detection import detect_gpus, best_encoder

            self._log_gpu_list = [g.name for g in detect_gpus()]
            enc = self.encoder_options.get("encoder", "cpu")
            self._log_enc_name = best_encoder() if enc == "auto" else enc
        except Exception:
            self._log_gpu_list = []
            self._log_enc_name = self.encoder_options.get("encoder", "cpu")

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
                self._logger.info(
                    f"🛠️ Override für '{display_name(path)}' gesetzt."
                )
                return True
            return False
        ok = worker.update_override(path, override)
        if ok:
            self.file_overrides[path] = dict(override or {})
        return ok

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

    def request_abort(self, mode: str = "sofort") -> None:
        self.abort_requested = True
        self.abort_type = mode
        if self._paused:
            self.resume()
        for worker in self._workers:
            if worker.isRunning():
                worker.request_abort(mode)

    def is_current(self, path: str) -> bool:
        return any(
            worker.isRunning() and hasattr(worker, "is_current") and worker.is_current(path)
            for worker in list(self._active_workers)
        )

    def terminate_current_ffmpeg(self, path: str | None = None) -> bool:
        for worker in list(self._active_workers):
            if not worker.isRunning():
                continue
            if path and hasattr(worker, "is_current") and not worker.is_current(path):
                continue
            if hasattr(worker, "terminate_current_ffmpeg") and worker.terminate_current_ffmpeg(path):
                return True
        return False

    def clear_abort_request(self) -> bool:
        """Nimmt einen vorgemerkten Abbruch nach Datei für den gesamten Lauf zurück."""
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

    def _start_child_worker(self, files: list[str]) -> ConverterThread:
        launcher = ParallelWorkerLauncher(
            worker_factory=ConverterThread,
            logger=self._logger,
            registry=self._registry,
            queue_state=self._queue_state,
        )
        return launcher.start(
            files,
            config=self.config,
            encoder_options=self.encoder_options,
            file_overrides=self.file_overrides,
            subtitle_rules=self.subtitle_rules,
            parent=self,
            paused=self._paused,
            abort_requested=self.abort_requested,
            abort_type=self.abort_type,
            log_emit=self.log_line.emit,
            event_emit=self.event.emit,
            relay_crop_decision=self._relay_dv_crop_decision,
            on_file_progress=self._on_child_file_progress,
            on_file_result=self._on_child_file_result,
            emit_progress=self._emit_aggregate_progress,
            on_finished=self._on_child_finished,
        )

    def _relay_dv_crop_decision(self, payload: object) -> None:
        self.dv_crop_decision_requested.emit(dict(payload or {}) if isinstance(payload, dict) else {})

    def provide_dv_crop_decision(self, request_id: str, decision: str) -> bool:
        return any(bool(getattr(worker, "provide_dv_crop_decision", lambda *_: False)(request_id, decision))
                   for worker in list(self._workers))

    def _on_child_file_progress(self, path: str, pct: int, eta_s) -> None:
        self._file_progress_pct[path] = int(pct)
        self.file_progress.emit(path, pct, eta_s)
        self._emit_aggregate_progress()

    def _on_child_file_result(
        self, child: ConverterThread, input_path: str, output_path: str, status: str
    ) -> None:
        self._child_results.on_file_result(
            child, input_path, output_path, status,
            abort_requested=self.abort_requested,
            start_pending_workers=self._start_pending_workers,
            emit_file_result=self.file_result.emit,
            emit_aggregate_progress=self._emit_aggregate_progress,
            finish_if_done=self._finish_if_done,
        )

    def _on_child_finished(self, child: ConverterThread) -> None:
        self._child_results.on_finished(
            child,
            abort_requested=self.abort_requested,
            start_pending_workers=self._start_pending_workers,
            emit_file_result=self.file_result.emit,
            emit_file_progress=self.file_progress.emit,
            logger_error=self._logger_error,
            emit_aggregate_progress=self._emit_aggregate_progress,
            finish_if_done=self._finish_if_done,
        )

    def _finish_if_done(self) -> None:
        if self._active_workers:
            return
        if self._postprocessing_workers:
            return
        if self._postprocessing_inputs:
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

    def _sync_child_maps(self, child: ConverterThread, input_path: str | None = None) -> None:
        self._result_state.sync_from_child(child, input_path)
        self._sync_replace_service()

    def _mark_child_unreported_files_failed(self, child: ConverterThread) -> None:
        self._child_results.mark_unreported_files_failed(
            child,
            emit_file_result=self.file_result.emit,
            emit_file_progress=self.file_progress.emit,
            logger_error=self._logger_error,
        )

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

    def _worker_load(self, worker: ConverterThread) -> int:
        try:
            current = 1 if getattr(worker._queue, "current_file", None) else 0
            return current + len(getattr(worker, "files", []) or [])
        except Exception:
            return 9999
