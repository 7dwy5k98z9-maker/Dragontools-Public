# -*- coding: utf-8 -*-
from __future__ import annotations
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox
from ..core.paths import display_name, strip_long_path_prefix
from ..worker.worker_contracts import RemoveFileStatus

class ConvertWidgetQueueRemoveMixin:
    def _remove_rejected_from_gui(self, rejected: list[str]) -> None:
        """
        Entfernt Dateien aus der GUI-Liste, die vom laufenden Worker nicht
        übernommen werden konnten (add_file() == False).
        Informiert den Nutzer explizit - kein stilles Entfernen.
        """
        if not rejected:
            return
        state = self.state
        for path in rejected:
            self.file_list.remove_path(path)
            state.file_overrides.pop(path, None)
            state.planned_targets.pop(path, None)
            self.log(
                f"⚠️ '{display_name(path)}' wurde aus der Liste entfernt - "
                "konnte nicht in die laufende Verarbeitung aufgenommen werden.",
                "warn",
            )
            self.log(
                f"Entfernter Pfad (Laenge {len(strip_long_path_prefix(path))}): "
                f"{strip_long_path_prefix(path)}",
                "warn",
            )
        names = "\n".join(f"• {display_name(p)}" for p in rejected)
        QMessageBox.warning(
            self.parent_widget,
            "Dateien nicht übernommen",
            f"Die folgenden Datei(en) konnten nicht in die laufende Verarbeitung "
            f"aufgenommen werden und wurden wieder aus der Liste entfernt:\n\n"
            f"{names}\n\n"
            "Mögliche Ursachen: Datei wird gerade verarbeitet, "
            "wurde bereits abgeschlossen oder ist bereits in der Queue.",
        )

    def sync_queue_order(self) -> None:
        if not self.guard_queue_edit_allowed("Reihenfolge aendern"):
            return
        thread = self.state.thread
        if not thread:
            return
        if not hasattr(thread, "reorder_waiting_files"):
            return

        new_order = self.file_list.get_paths()
        thread.reorder_waiting_files(new_order)

    def remove_path(self, path: str) -> None:
        self.remove_paths([path])

    def _normalize_remove_status(self, state) -> RemoveFileStatus:
        if isinstance(state, RemoveFileStatus):
            return state
        return RemoveFileStatus(state)

    def _remove_local_entry(self, path: str) -> None:
        state = self.state
        self.file_list.remove_path(path)
        state.file_overrides.pop(path, None)
        state.planned_targets.pop(path, None)
        getattr(state, "preflight_rows_by_path", {}).pop(path, None)
        state.pending_remove_paths.discard(path)

    def remove_paths(self, paths: list[str]) -> None:
        if paths and not self.guard_queue_edit_allowed("Dateien entfernen"):
            return
        state_obj = self.state
        thread = state_obj.thread
        for path in paths:
            remove_state = RemoveFileStatus.REMOVED
            worker_error = False

            if thread and hasattr(thread, "remove_file"):
                try:
                    remove_state = self._normalize_remove_status(thread.remove_file(path))
                    self.log(f"remove_file({display_name(path)}) -> {remove_state.value}", "info")
                except Exception as exc:
                    self.log(
                        f"Entfernen aus Thread-Queue fehlgeschlagen: {display_name(path)} - {exc}",
                        "warn",
                    )
                    remove_state = RemoveFileStatus.NOT_FOUND
                    worker_error = True

            if remove_state == RemoveFileStatus.PENDING_REMOVE:
                state_obj.pending_remove_paths.add(path)
                for i in range(self.file_list.count()):
                    item = self.file_list.item(i)
                    if item and item.data(Qt.ItemDataRole.UserRole) == path:
                        item.setText(f"(läuft - wird nach Abschluss aus der Liste entfernt)  {display_name(path)}")
                        break
                continue

            if remove_state == RemoveFileStatus.CURRENT:
                state_obj.pending_remove_paths.add(path)
                self.log(
                    f"'{display_name(path)}' ist bereits zur Entfernung nach Abschluss vorgemerkt.",
                    "info",
                )
                continue

            if remove_state == RemoveFileStatus.NOT_FOUND and thread and worker_error:
                self.log(
                    f"Datei konnte nicht sicher aus der Worker-Queue entfernt werden: {display_name(path)}",
                    "warn",
                )
                continue

            self._remove_local_entry(path)

        self._sync_total_files()

    def remove_selected(self) -> None:
        paths = [
            item.data(Qt.ItemDataRole.UserRole)
            for item in self.file_list.selectedItems()
        ]
        self.remove_paths(paths)

    def clear(self) -> None:
        if not self.guard_queue_edit_allowed("Warteschlange leeren"):
            return
        state = self.state
        thread = state.thread
        current_paths: set[str] = set()

        if thread and hasattr(thread, "remove_file"):
            for path in list(self.file_list.get_paths()):
                try:
                    remove_state = self._normalize_remove_status(thread.remove_file(path))
                    if remove_state in {RemoveFileStatus.PENDING_REMOVE, RemoveFileStatus.CURRENT}:
                        state.pending_remove_paths.add(path)
                        current_paths.add(path)
                except Exception as exc:
                    current_paths.add(path)
                    self.log(
                        f"Entfernen aus Thread-Queue fehlgeschlagen: {display_name(path)} - {exc}",
                        "warn",
                    )

        for path in list(self.file_list.get_paths()):
            if path not in current_paths:
                self._remove_local_entry(path)

        if self.file_list.count() == 0:
            state.file_overrides.clear()
            state.planned_targets.clear()
            state.pending_remove_paths.clear()
            state.fertig.clear()
            self.reset_progress_ui()

        self._sync_total_files()
