# -*- coding: utf-8 -*-
from __future__ import annotations


class ConvertWidgetQueueManagementMixin:

    def add_dropped_files(self, paths: list[str]) -> None:
        if not self._guard_queue_edit_allowed("Dateien hinzufügen"):
            return
        self._file_queue.on_files_dropped(paths)
        self._refresh_queue_window()

    def _add_files(self):
        self._file_queue.add_files()
        self._refresh_queue_window()

    def _add_folder(self):
        self._file_queue.add_folder()
        self._refresh_queue_window()

    def _sync_queue_order(self):
        if not self._guard_queue_edit_allowed("Reihenfolge aendern"):
            return
        self._file_queue.sync_queue_order()
        self._refresh_queue_window()

    def _remove_path(self, path: str):
        if not self._guard_queue_edit_allowed("Dateien entfernen"):
            return
        self._file_queue.remove_path(path)
        self._refresh_queue_window()

    def _remove_paths(self, paths: list[str]):
        if paths and not self._guard_queue_edit_allowed("Dateien entfernen"):
            return
        self._file_queue.remove_paths(paths)
        self._refresh_queue_window()

    def remove_selected_files(self):
        if not self._guard_queue_edit_allowed("Dateien entfernen"):
            return
        self._file_queue.remove_selected()
        self._refresh_queue_window()

    def _clear(self):
        if self._is_queue_blocking_move_active():
            self._log("Warteschlange w\u00e4hrend Verschieben gesperrt: Warteschlange leeren.", "warn")
            return
        self._state.completed_inputs.clear()
        self._state.pending_remove_paths.clear()
        self._file_queue.clear()
        self._refresh_queue_window()
