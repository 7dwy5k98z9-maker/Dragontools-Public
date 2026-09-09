# -*- coding: utf-8 -*-
"""Schlanker Orchestrator für Preflight und Move-GUI.

Fachliche Verantwortungen liegen in Workflow-, Lifecycle- und Dialog-Services.
Der Controller exponiert nur die von der GUI tatsächlich benötigte öffentliche API.
"""
from __future__ import annotations

from typing import Any, Callable

from ..worker.move_thread import MoveThread
from .conversion_session_state import ConversionSessionState
from .convert_widget_layout import ConvertWidgetUI
from .move_preflight_workflow import MovePreflightWorkflow
from .move_lifecycle_coordinator import MoveLifecycleCoordinator
from .move_request_dialogs import MoveRequestDialogHandler


class MovePreflightController:
    """Koordiniert Preflight-Workflow, Move-Lifecycle und Benutzerentscheidungen."""

    def __init__(
        self,
        *,
        state: ConversionSessionState,
        ui: ConvertWidgetUI,
        log: Callable,
        parent_widget,
        get_target_paths: Callable,
        finalize_run: Callable,
        set_start_enabled: Callable,
        set_queue_edit: Callable,
        refresh_queue: Callable,
        remove_queued_files: Callable | None = None,
        preflight_rows_builder: Callable[[list[str], dict[str, Any]], list[dict[str, Any]]] | None = None,
    ) -> None:
        self._state = state
        self._ui = ui
        self._log = log
        self._parent = parent_widget
        self._get_target_paths = get_target_paths
        self._finalize_run = finalize_run
        self._set_start_enabled = set_start_enabled
        self._set_queue_edit = set_queue_edit
        self._refresh_queue = refresh_queue
        self._remove_queued_files = remove_queued_files
        self._preflight_rows_builder = preflight_rows_builder

        self._requests = MoveRequestDialogHandler(
            state=state,
            log=lambda *args, **kwargs: self._log(*args, **kwargs),
            parent=parent_widget,
        )
        self._workflow = MovePreflightWorkflow(
            state=state,
            ui=ui,
            log=lambda *args, **kwargs: self._log(*args, **kwargs),
            parent=parent_widget,
            get_target_paths=get_target_paths,
            remove_queued_files=remove_queued_files,
            rows_builder_getter=lambda: self._preflight_rows_builder,
        )
        self._lifecycle = MoveLifecycleCoordinator(
            state=state,
            ui=ui,
            log=lambda *args, **kwargs: self._log(*args, **kwargs),
            parent=parent_widget,
            get_target_paths=get_target_paths,
            finalize_run=finalize_run,
            set_start_enabled=set_start_enabled,
            set_queue_edit=set_queue_edit,
            refresh_queue=refresh_queue,
            worker_factory=lambda *args, **kwargs: MoveThread(*args, **kwargs),
            on_move_req=lambda rid, payload: self.on_move_req(rid, payload),
            set_file_text=lambda path, text: self.set_file_list_item_text(path, text),
        )

    # Preflight workflow
    def run_if_needed(self, files: list[str]) -> bool:
        return self._workflow.run_if_needed(files)

    def maybe_for_new_files(self, added: list[str]) -> None:
        self._workflow.maybe_for_new_files(added)

    def save_report(self, files, planned_targets, target_paths, *, title):
        return self._workflow.save_report(files, planned_targets, target_paths, title=title)

    # Move lifecycle
    def start_move(self, files: list[str], finished_thread) -> None:
        self._lifecycle.start_move(files, finished_thread)

    def move_finished_now(self) -> None:
        self._lifecycle.move_finished_now()

    def collect_finished_move_candidates(self) -> list[str]:
        return self._lifecycle.collect_finished_move_candidates()

    def start_incremental_move(self, files: list[str]) -> None:
        self._lifecycle.start_incremental_move(files)

    def finish_incremental_move(self, move_thread=None) -> None:
        self._lifecycle.finish_incremental_move(move_thread)

    def retire_move_thread(self, move_thread) -> None:
        self._lifecycle.retire_move_thread(move_thread)

    def successful_video_sources(self, move_log: list) -> set[str]:
        return self._lifecycle.successful_video_sources(move_log)

    def input_paths_for_output(self, output_path: str) -> list[str]:
        return self._lifecycle.input_paths_for_output(output_path)

    def set_file_list_item_text(self, path: str, text: str) -> None:
        from .ui_helpers import set_file_list_item_text
        set_file_list_item_text(self._ui.file_list, path, text)

    # MoveThread user requests
    def on_move_req(self, rid: str, payload: dict) -> None:
        self._requests.on_move_req(rid, payload)

    def film_destination_dialog(self, rid: str, payload: dict) -> None:
        self._requests.film_destination_dialog(rid, payload)

    def handle_series_base_or_folder(self, rid: str, payload: dict) -> None:
        self._requests.handle_series_base_or_folder(rid, payload)

    def handle_series_folder(self, rid: str, payload: dict) -> None:
        self._requests.handle_series_folder(rid, payload)

    def handle_shutdown_countdown(self, rid: str, payload: dict) -> None:
        self._requests.handle_shutdown_countdown(rid, payload)
