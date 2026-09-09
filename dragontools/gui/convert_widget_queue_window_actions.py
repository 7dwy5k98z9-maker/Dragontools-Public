# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListWidgetItem

from .convert_queue_window import ConvertQueueWindow
from ..core.paths import display_name


class ConvertWidgetQueueWindowActionsMixin:

    def _requeue_paths(self, paths: list[str]) -> None:
        added = 0
        for path in paths or []:
            self._state.completed_inputs.discard(path)
            self._state.pending_remove_paths.discard(path)
            if self.file_list.add_path(path):
                added += 1
            else:
                self._log(f"Fehlerdatei konnte nicht erneut eingereiht werden: {display_name(path)}", "warn")
        self._total_files = self.file_list.count()
        self._refresh_queue_window()
        if added:
            self._log(f"{added} Datei(en) für erneuten Start bereit.", "info")

    def open_queue_window(self) -> None:
        if self._queue_window is not None:
            self._queue_window.refresh_from_owner()
            self._queue_window.show()
            self._queue_window.raise_()
            self._queue_window.activateWindow()
            return
        self._queue_window = ConvertQueueWindow(
            self,
            default_codec=self.default_codec,
            source_list=self.file_list,
            is_queue_blocking_move_active=self._is_queue_blocking_move_active,
            active_worker=self._active_worker,
            apply_queue_order=self._apply_queue_window_order,
            toggle_pause=self._toggle_pause,
            abort=self._abort,
            on_closed=lambda: setattr(self, "_queue_window", None),
        )
        self._queue_window.show()
        self._queue_window.raise_()
        self._queue_window.activateWindow()

    def _refresh_queue_window(self) -> None:
        if hasattr(self, "_ui") and hasattr(self._ui, "move_finished_btn"):
            worker_running = bool(
                self._state.thread and self._state.thread.isRunning()
            )
            self._ui.move_finished_btn.setEnabled(
                bool(getattr(self._state, "fertig", set()))
                and worker_running
                and not self._is_move_active()
            )
        if self._queue_window is not None:
            self._queue_window.schedule_refresh_from_owner()

    def _apply_queue_window_order(self, new_order: list[str]) -> None:
        if not self._guard_queue_edit_allowed("Reihenfolge aendern"):
            return
        old_state: dict[str, dict] = {}
        for i in range(self._ui.file_list.count()):
            item = self._ui.file_list.item(i)
            if item is None:
                continue
            path = item.data(Qt.ItemDataRole.UserRole)
            old_state[path] = {"text": item.text(), "selected": item.isSelected()}

        self._ui.file_list.clear()
        for path in new_order:
            item = QListWidgetItem(old_state.get(path, {}).get("text", display_name(path)))
            item.setData(Qt.ItemDataRole.UserRole, path)
            self._ui.file_list.addItem(item)
            if old_state.get(path, {}).get("selected"):
                item.setSelected(True)
        if hasattr(self._ui.file_list, "rebuild_path_index"):
            self._ui.file_list.rebuild_path_index()
        self._ui.file_list.update_empty_banner()

        self._sync_queue_order()
