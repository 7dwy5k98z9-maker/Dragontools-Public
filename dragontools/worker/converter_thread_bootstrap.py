# -*- coding: utf-8 -*-
"""Composition/bootstrap boundary for ``ConverterThread`` construction."""
from __future__ import annotations

from PyQt6.QtCore import QSettings

from ..core.gpu_detection import best_encoder, detect_gpus
from ..core.logger import create_verbose_logger, create_worker_logger
from ..core.settings_app import APP_NAME, APP_ORG
from .converter_control import ConverterControlService
from .converter_file_executor import ConverterFileExecutor
from .converter_lifecycle import ConverterLifecycleService
from .converter_queue_state import ConverterQueueState
from .converter_run_loop import ConverterRunLoop
from .converter_runtime_builder import ConverterRuntimeBuilder
from .converter_static_composition import build_static_converter_services
from .converter_thread_state import ConverterControlState, ConverterJobState, ConverterSessionState
from .dv_runtime_models import DVTempState
from .worker_runtime_state import WorkerRuntimeState


def _detect_log_gpu_context(job: ConverterJobState) -> tuple[list[str], str]:
    """Best-effort GPU header data; logging must never prevent worker creation."""
    encoder = job.encoder_options.get("encoder", "cpu")
    try:
        gpu_list = [gpu.name for gpu in detect_gpus()]
        encoder_name = best_encoder() if encoder == "auto" else encoder
        return gpu_list, encoder_name
    except Exception:
        return [], encoder


def bootstrap_converter_thread(worker, files, config, *, shared_logger=None) -> None:
    """Install state, logging, static services and run orchestrators on ``worker``.

    The function is intentionally the sole construction composition root for the
    QThread facade. Runtime-dependent pipeline services are still created later
    by ``ConverterRuntimeBuilder`` when ``run()`` starts.
    """
    input_files = list(files)
    worker.config = config
    worker._job_state = ConverterJobState.from_config(config)
    worker._control_state = ConverterControlState()
    worker._session_state = ConverterSessionState(all_input_files=input_files)
    worker._queue = ConverterQueueState(input_files)
    worker.files = worker._queue.files
    worker._files_lock = worker._queue.lock
    worker._runtime_state = WorkerRuntimeState(total_count=worker._queue.initial_total)
    worker._temp_state = DVTempState()

    worker._log_gpu_list, worker._log_enc_name = _detect_log_gpu_context(worker._job_state)

    worker.settings = QSettings(APP_ORG, APP_NAME)
    worker._logger = shared_logger or create_worker_logger(
        settings=worker.settings,
        log_file_path=config.log_file_path,
        gui_callback=worker.log_line.emit,
    )
    worker.log_file_path = str(worker._logger.log_file) if worker._logger.log_file else None
    worker._verbose_logger = create_verbose_logger(settings=worker.settings)

    worker._services = build_static_converter_services(
        worker,
        job=worker._job_state,
        settings=worker.settings,
        logger=worker._logger,
        runtime_state=worker._runtime_state,
        failure_details=worker._session_state.failure_details,
    )

    worker._runtime_builder = ConverterRuntimeBuilder(worker)
    worker._run_loop = ConverterRunLoop(worker)
    worker._lifecycle = ConverterLifecycleService(worker)
    worker._file_executor = ConverterFileExecutor(worker)
    worker._control = ConverterControlService(worker, worker._control_state)
