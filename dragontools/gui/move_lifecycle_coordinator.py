# -*- coding: utf-8 -*-
"""Schmale Fassade für regulären und inkrementellen Move-Lifecycle."""
from __future__ import annotations

from .move_incremental_lifecycle import IncrementalMoveLifecycle
from .move_lifecycle_helpers import input_paths_for_output, retire_move_thread, successful_video_sources
from .move_regular_lifecycle import RegularMoveLifecycle


class MoveLifecycleCoordinator:
    def __init__(
        self,
        *,
        state,
        ui,
        log,
        parent,
        get_target_paths,
        finalize_run,
        set_start_enabled,
        set_queue_edit,
        refresh_queue,
        worker_factory,
        on_move_req,
        set_file_text,
    ) -> None:
        self._state = state
        self._set_file_text = set_file_text
        common = dict(
            state=state,
            ui=ui,
            log=log,
            get_target_paths=get_target_paths,
            set_start_enabled=set_start_enabled,
            set_queue_edit=set_queue_edit,
            refresh_queue=refresh_queue,
            worker_factory=worker_factory,
            on_move_req=on_move_req,
        )
        self._regular = RegularMoveLifecycle(finalize_run=finalize_run, **common)
        self._incremental = IncrementalMoveLifecycle(
            parent=parent,
            set_file_text=lambda path, text: self.set_file_list_item_text(path, text),
            **common,
        )

    def start_move(self, files: list[str], finished_thread) -> None:
        self._regular.start(files, finished_thread)

    def move_finished_now(self) -> None:
        self._incremental.prompt_and_start()

    def collect_finished_move_candidates(self) -> list[str]:
        return self._incremental.collect_candidates()

    def start_incremental_move(self, files: list[str]) -> None:
        self._incremental.start(files)

    def finish_incremental_move(self, move_thread=None) -> None:
        self._incremental.finish(move_thread)

    def retire_move_thread(self, move_thread) -> None:
        retire_move_thread(self._state, move_thread)

    def successful_video_sources(self, move_log: list) -> set[str]:
        return successful_video_sources(move_log)

    def input_paths_for_output(self, output_path: str) -> list[str]:
        return input_paths_for_output(self._state.run_results, output_path)

    def set_file_list_item_text(self, path: str, text: str) -> None:
        self._set_file_text(path, text)
