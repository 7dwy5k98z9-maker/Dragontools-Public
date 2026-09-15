# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import replace

from ..core.callback_dispatch import invoke_callback
from ..core.path_syntax import path_compare_key


class ParallelWorkerLauncher:
    """Erzeugt und verdrahtet genau einen Converter-Child-Worker ohne Qt-Import."""

    def __init__(self, *, worker_factory, logger, registry, queue_state) -> None:
        self._worker_factory = worker_factory
        self._logger = logger
        self._registry = registry
        self._queue_state = queue_state

    def start(
        self,
        files: list[str],
        *,
        config,
        encoder_options: dict,
        file_overrides: dict,
        subtitle_rules: dict,
        parent,
        paused: bool,
        abort_requested: bool,
        abort_type: str | None,
        log_emit,
        event_emit,
        relay_crop_decision,
        on_file_progress,
        on_file_result,
        emit_progress,
        on_finished,
    ):
        child_config = replace(
            config,
            encoder_options=dict(encoder_options),
            file_overrides=dict(file_overrides),
            subtitle_rules=dict(subtitle_rules),
        )
        worker = self._worker_factory(files, child_config, shared_logger=self._logger, parent=parent)
        worker._suppress_session_header = True
        worker._display_index_by_path = self._queue_state.display_index_by_path
        worker._display_total = self._queue_state.display_total
        worker.log_line.connect(lambda message: invoke_callback(log_emit, message))
        worker.event.connect(lambda event: invoke_callback(event_emit, event))
        if hasattr(worker, "dv_crop_decision_requested"):
            worker.dv_crop_decision_requested.connect(
                lambda payload: invoke_callback(relay_crop_decision, payload)
            )
        worker.file_progress.connect(
            lambda path, pct, eta: invoke_callback(on_file_progress, path, pct, eta)
        )
        worker.file_result.connect(
            lambda input_path, output_path, status, child=worker: invoke_callback(
                on_file_result, child, input_path, output_path, status
            )
        )
        worker.progress.connect(lambda _pct: invoke_callback(emit_progress))
        worker.finished.connect(lambda child=worker: invoke_callback(on_finished, child))
        self._registry.workers.append(worker)
        self._registry.active_workers.add(worker)
        for path in files:
            self._queue_state.assigned[path_compare_key(path)] = worker
        if paused:
            worker.pause()
        if abort_requested:
            worker.request_abort(abort_type or "sofort")
        worker.start()
        return worker
