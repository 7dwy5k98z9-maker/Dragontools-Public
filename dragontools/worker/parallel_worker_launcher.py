# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import replace
from copy import deepcopy
from .parallel_queue_coordination import coordinated_change
from .parallel_launch_ownership import child_may_be_running, release_unstarted_child
from .log_dispatch import dispatch_log

from ..core.callback_dispatch import invoke_callback
from ..core.path_syntax import path_compare_key


class ParallelWorkerLauncher:
    """Erzeugt und verdrahtet genau einen Converter-Child-Worker ohne Qt-Import."""

    def __init__(self, *, worker_factory, logger, registry, queue_state) -> None:
        self._worker_factory = worker_factory
        self._logger = logger
        self._registry = registry
        self._queue_state = queue_state

    @coordinated_change
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
        on_encode_stage_complete,
        dv_postprocess_gate,
        emit_progress,
        on_finished,
        on_owned_file_progress=None,
    ):
        assigned_keys = [path_compare_key(path) for path in files]
        if (not assigned_keys or any(not key for key in assigned_keys)
                or len(set(assigned_keys)) != len(assigned_keys)
                or any(key in self._queue_state.assigned for key in assigned_keys)):
            raise ValueError("Quelldatei besitzt bereits einen Worker oder ist kein eindeutiger Queue-Eintrag.")
        child_config = replace(
            config,
            encoder_options=deepcopy(encoder_options),
            file_overrides=deepcopy(file_overrides),
            subtitle_rules=deepcopy(subtitle_rules),
        )
        worker = self._worker_factory(files, child_config, shared_logger=self._logger, parent=parent)
        worker._suppress_session_header = True
        worker._enable_dv_encode_overlap = True
        worker._dv_postprocess_gate = dv_postprocess_gate
        worker._display_index_by_path = self._queue_state.display_index_by_path
        worker._display_total = self._queue_state.display_total
        worker.log_line.connect(lambda message: invoke_callback(log_emit, message))
        worker.worker_event.connect(lambda event: invoke_callback(event_emit, event))
        if hasattr(worker, "dv_crop_decision_requested"):
            worker.dv_crop_decision_requested.connect(
                lambda payload: invoke_callback(relay_crop_decision, payload)
            )
        if on_owned_file_progress is None:
            worker.file_progress.connect(
                lambda path, pct, eta: invoke_callback(on_file_progress, path, pct, eta)
            )
        else:
            worker.file_progress.connect(
                lambda path, pct, eta, child=worker: invoke_callback(
                    on_owned_file_progress, child, path, pct, eta
                )
            )
        worker.file_result.connect(
            lambda input_path, output_path, status, child=worker: invoke_callback(
                on_file_result, child, input_path, output_path, status
            )
        )
        if hasattr(worker, "encode_stage_complete"):
            worker.encode_stage_complete.connect(
                lambda input_path, output_path, child=worker: invoke_callback(
                    on_encode_stage_complete, child, input_path, output_path
                )
            )
        worker.progress.connect(lambda _pct: invoke_callback(emit_progress))
        worker.finished.connect(lambda child=worker: invoke_callback(on_finished, child))
        self._registry.workers.append(worker)
        self._registry.active_workers.add(worker)
        for key in assigned_keys:
            self._queue_state.assigned[key] = worker
        try:
            if paused:
                worker.pause()
            if abort_requested:
                worker.request_abort(abort_type or "sofort")
            worker.start()
        except Exception as exc:
            if child_may_be_running(worker):
                dispatch_log(self._logger,
                    f"Worker meldete einen Startfehler, ist jedoch aktiv und bleibt dem Lauf zugeordnet: {exc}", "warn")
                return worker
            # Child ownership is transactional: a worker that never started
            # must not reserve paths or an active slot indefinitely.
            release_unstarted_child(self._registry, self._queue_state, worker, assigned_keys)
            raise
        return worker
