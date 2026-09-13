# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

from PyQt6.QtCore import QObject, QSettings, pyqtSignal

from ..core.logger import create_worker_logger
from ..core.parallel_settings import clamp_parallel_jobs
from ..core.settings import APP_NAME, APP_ORG
from .converter_config import ConverterConfig
from .converter_thread import ConverterThread
from .parallel_child_result_coordinator import ParallelChildResultCoordinator
from .parallel_converter_compat import ParallelConverterCompatibilityMixin
from .parallel_converter_control import ParallelConverterControlMixin
from .parallel_converter_lifecycle import ParallelConverterLifecycleMixin
from .parallel_converter_queue import ParallelConverterQueueMixin
from .parallel_converter_state import ParallelQueueState, ParallelResultState, ParallelWorkerRegistry
from .parallel_worker_launcher import ParallelWorkerLauncher


class ParallelConverterThread(
    ParallelConverterCompatibilityMixin,
    ParallelConverterQueueMixin,
    ParallelConverterControlMixin,
    ParallelConverterLifecycleMixin,
    QObject,
):
    """Qt-facing coordinator for multiple normal ConverterThread instances."""

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
            self._queue_state,
            self._result_state,
            replace_service=self._replace_service_summary,
        )
        self._child_results = ParallelChildResultCoordinator(
            registry=self._registry,
            queue_state=self._queue_state,
            result_state=self._result_state,
        )

        self._logger = create_worker_logger(
            settings=QSettings(APP_ORG, APP_NAME),
            gui_callback=self.log_line.emit,
        )
        self.log_file_path = str(self._logger.log_file) if self._logger.log_file else None
        self._run_start_ts: float | None = None
        self._initialize_gpu_log_context()

    def _initialize_gpu_log_context(self) -> None:
        try:
            from ..core.gpu_detection import best_encoder, detect_gpus

            self._log_gpu_list = [gpu.name for gpu in detect_gpus()]
            encoder = self.encoder_options.get("encoder", "cpu")
            self._log_enc_name = best_encoder() if encoder == "auto" else encoder
        except Exception:
            self._log_gpu_list = []
            self._log_enc_name = self.encoder_options.get("encoder", "cpu")

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

    def _on_child_file_progress(self, path: str, pct: int, eta_s) -> None:
        self._file_progress_pct[path] = int(pct)
        self.file_progress.emit(path, pct, eta_s)
        self._emit_aggregate_progress()

    def _on_child_file_result(
        self,
        child: ConverterThread,
        input_path: str,
        output_path: str,
        status: str,
    ) -> None:
        self._child_results.on_file_result(
            child,
            input_path,
            output_path,
            status,
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

    def _worker_load(self, worker: ConverterThread) -> int:
        try:
            current = 1 if getattr(worker._queue, "current_file", None) else 0
            return current + len(getattr(worker, "files", []) or [])
        except Exception:
            return 9999
