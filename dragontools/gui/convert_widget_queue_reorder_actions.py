# -*- coding: utf-8 -*-
from __future__ import annotations

from .queue_ordering import MOVE_BACK, MOVE_DOWN, MOVE_FRONT, MOVE_UP, reorder_selected_paths


class ConvertWidgetQueueReorderActionsMixin:
    def _active_queue_paths(self) -> list[str]:
        thread = self._state.thread
        if thread is None or not hasattr(thread, "is_current"):
            return []
        active: list[str] = []
        for path in self.file_list.get_paths():
            try:
                if thread.is_current(path):
                    active.append(path)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                continue
        return active

    def _move_selected_queue(self, action: str) -> None:
        if not self._guard_queue_edit_allowed("Reihenfolge aendern"):
            return
        selected = self.file_list.selected_paths_in_order()
        if not selected:
            return
        current = self.file_list.get_paths()
        new_order = reorder_selected_paths(
            current,
            selected,
            self._active_queue_paths(),
            action=action,
        )
        if new_order == current:
            return
        if self.file_list.apply_path_order(new_order):
            self._sync_queue_order()
            self._refresh_queue_window()

    def _queue_move_up(self) -> None:
        self._move_selected_queue(MOVE_UP)

    def _queue_move_down(self) -> None:
        self._move_selected_queue(MOVE_DOWN)

    def _queue_move_front(self) -> None:
        self._move_selected_queue(MOVE_FRONT)

    def _queue_move_back(self) -> None:
        self._move_selected_queue(MOVE_BACK)
