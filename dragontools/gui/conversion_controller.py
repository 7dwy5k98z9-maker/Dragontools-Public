# -*- coding: utf-8 -*-
"""Schmale GUI-Fassade für den Conversion-Workflow.

Der Controller koordiniert nur noch spezialisierte Services:

* :mod:`conversion_start_coordinator` – Start-Workflows
* :mod:`conversion_worker_factory` – ConverterConfig und Worker-Erzeugung
* :mod:`conversion_worker_lifecycle` – Pause/Abort/Signal-Lifecycle
* :mod:`conversion_progress_presenter` – Fortschrittsanzeige
* :mod:`conversion_diagnostics` – Diagnoseformatierung

Damit enthält diese Klasse keine Encoder-, Fortschritts- oder Worker-Factory-
Businesslogik mehr.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from .conversion_diagnostics import ConversionDiagnosticsService
from .conversion_progress_presenter import (
    ConversionProgressPresenter,
)
from .conversion_start_coordinator import ConversionStartCoordinator
from .conversion_worker_factory import ConversionConfigBuilder, ConversionWorkerFactory
from .conversion_worker_lifecycle import ConversionWorkerLifecycle
from .conversion_session_state import ConversionSessionState
from .ui_helpers import set_file_list_item_text

if TYPE_CHECKING:
    from .convert_widget_layout import ConvertWidgetUI
    from .move_preflight_controller import MovePreflightController
    from .conversion_result_service import ConversionResultService


class ConversionController:
    """Orchestriert die spezialisierten Conversion-GUI-Services."""

    def __init__(
        self,
        *,
        state: ConversionSessionState,
        ui: ConvertWidgetUI,
        default_codec: str,
        log: Callable,
        collect_encoder_options: Callable,
        get_target_paths: Callable,
        refresh_queue: Callable,
        set_start_enabled: Callable,
        set_queue_edit: Callable,
        preflight: "MovePreflightController",
        result_service: "ConversionResultService",
        qt_parent,
        remove_queued_files: Callable[[list[str]], None] | None = None,
    ) -> None:
        self._state = state
        self._ui = ui
        self._default_codec = default_codec
        self._log = log
        self._collect_encoder_options = collect_encoder_options
        self._get_target_paths = get_target_paths
        self._refresh_queue = refresh_queue
        self._set_start_enabled = set_start_enabled
        self._set_queue_edit = set_queue_edit
        self._remove_queued_files = remove_queued_files
        self._preflight = preflight
        self._result_service = result_service
        self._qt_parent = qt_parent

        self._config_builder = ConversionConfigBuilder(
            state=state,
            ui=ui,
            default_codec=default_codec,
            collect_encoder_options=collect_encoder_options,
            get_target_paths=get_target_paths,
            log=log,
        )
        self._worker_factory = ConversionWorkerFactory(
            config_builder=self._config_builder,
            qt_parent=qt_parent,
        )
        self._progress = ConversionProgressPresenter(
            state=state,
            ui=ui,
            log=log,
            refresh_queue=refresh_queue,
            set_file_list_item_text=lambda path, text: set_file_list_item_text(self._ui.file_list, path, text),
        )
        self._lifecycle = ConversionWorkerLifecycle(
            state=state,
            ui=ui,
            log=log,
            set_start_enabled=set_start_enabled,
            refresh_queue=refresh_queue,
            result_service=result_service,
            progress_presenter=self._progress,
            default_codec=default_codec,
            collect_encoder_options=collect_encoder_options,
        )
        self._start_coordinator = ConversionStartCoordinator(
            state=state,
            ui=ui,
            log=log,
            collect_encoder_options=collect_encoder_options,
            get_target_paths=get_target_paths,
            refresh_queue=refresh_queue,
            set_start_enabled=set_start_enabled,
            set_queue_edit=set_queue_edit,
            preflight=preflight,
            worker_factory=self._worker_factory,
            lifecycle=self._lifecycle,
            progress_presenter=self._progress,
            qt_parent=qt_parent,
        )
        self._diagnostics = ConversionDiagnosticsService(state=state)

    # ── Öffentliche API ─────────────────────────────────────────────

    def active_worker(self):
        return self._lifecycle.active_worker()

    def workers_for_shutdown(self) -> tuple:
        return self._lifecycle.workers_for_shutdown()

    def get_start_files(self) -> list[str]:
        return self._start_coordinator.get_start_files()

    def start_convert(self) -> None:
        self._start_coordinator.start_convert()

    def start_move_only(self) -> None:
        self._start_coordinator.start_move_only()

    def start_dv_remux(self) -> None:
        self._start_coordinator.start_dv_remux()

    def toggle_pause(self) -> None:
        self._lifecycle.toggle_pause()

    def is_file_active(self, path: str) -> bool:
        return self._lifecycle.is_file_active(path)

    def terminate_current_ffmpeg(self, path: str) -> bool:
        return self._lifecycle.terminate_current_ffmpeg(path)

    def abort(self) -> None:
        self._lifecycle.abort()

    def on_total_progress(self, pct: int) -> None:
        self._progress.on_total_progress(pct)

    def on_file_progress(self, path: str, pct: int, eta_s) -> None:
        self._progress.on_file_progress(path, pct, eta_s)

    def running_job_diagnostics(self) -> str:
        return self._diagnostics.report(self.active_worker())

    def reset_run_state(self, file_count: int) -> None:
        self._progress.reset(file_count)

    def get_subtitle_rules(self) -> dict:
        return self._config_builder.subtitle_rules()
