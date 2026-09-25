# -*- coding: utf-8 -*-
"""Runtime editing of planned move destinations for converter queue items."""
from __future__ import annotations


from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from ..core.path_syntax import user_path_name, user_path_parent
from ..core.planned_target_edit import rebase_series_target, series_root_from_target, target_kind
from ..rules.move_rules import planned_target_dir


class ConvertWidgetQueueTargetActionsMixin:
    def _context_selected_paths(self, clicked_path: str) -> list[str]:
        selected = [
            str(item.data(Qt.ItemDataRole.UserRole))
            for item in self._ui.file_list.selectedItems()
            if item.data(Qt.ItemDataRole.UserRole)
        ]
        return [clicked_path, *[path for path in selected if path != clicked_path]] if clicked_path in selected else [clicked_path]

    def _planned_target_storage_key(self, input_path: str) -> str:
        state = self._state
        bundle = state.artifacts_by_input.get(input_path)
        output_path = str(getattr(bundle, "output_path", "") or "") if bundle is not None else ""
        if output_path and output_path in state.planned_targets:
            return output_path
        if input_path in state.planned_targets:
            return input_path
        return output_path or input_path

    def _target_edit_rows(self, paths: tuple[str, ...]) -> list[tuple[str, str, object]]:
        rows = []
        for input_path in (str(path) for path in paths if path):
            key = self._planned_target_storage_key(input_path)
            rows.append((input_path, key, self._state.planned_targets.get(key)))
        return rows

    def _choose_replacement_targets(self, rows: list[tuple[str, str, object]]) -> dict[str, str] | None:
        kinds = {target_kind(path, current) for path, _key, current in rows}
        if len(kinds) != 1:
            QMessageBox.warning(
                self,
                "Zielordner ändern",
                "Serienfolgen und Filme können nicht gemeinsam auf ein neues Ziel gesetzt werden.",
            )
            return None

        first_target = planned_target_dir(rows[0][2])
        if next(iter(kinds)) == "series":
            initial = series_root_from_target(rows[0][2]) or (user_path_parent(first_target) if first_target else "")
            chosen = QFileDialog.getExistingDirectory(
                self,
                "Neuen Serien-Zielordner wählen – Staffelordner bleibt erhalten",
                initial,
            )
            if not chosen:
                return None
            try:
                return {
                    input_path: rebase_series_target(input_path, current, chosen)
                    for input_path, _key, current in rows
                }
            except ValueError as exc:
                QMessageBox.warning(self, "Zielordner ändern", str(exc))
                return None

        if len(rows) > 1:
            QMessageBox.warning(
                self,
                "Zielordner ändern",
                "Mehrere Filme erhalten absichtlich nicht gemeinsam denselben vollständigen Zielordner. "
                "Bitte ändere Filmziele einzeln.",
            )
            return None
        chosen = QFileDialog.getExistingDirectory(
            self,
            "Vollständigen neuen Film-Zielordner wählen",
            first_target or "",
        )
        if not chosen:
            return None
        return {input_path: str(chosen) for input_path, _key, _current in rows}

    def _apply_replacement_targets(
        self,
        input_paths: tuple[str, ...],
        replacements: dict[str, str],
    ) -> list[str]:
        """Apply a confirmed edit to the *current* storage key.

        The folder dialog runs a nested Qt event loop.  A conversion may finish
        while it is open, moving the planned-target entry from the input path
        to the output path.  Therefore keys captured before opening the dialog
        are stale by definition and must never be used for the commit.
        """
        rejected: list[str] = []
        move_thread = self._state.move_thread
        move_running = bool(move_thread and move_thread.isRunning())
        move_paths = set(getattr(move_thread, "dateipfade", []) or []) if move_running else set()

        for input_path in (str(path) for path in input_paths if path):
            target = replacements.get(input_path)
            if not target:
                continue

            # Re-resolve AFTER the dialog has closed.  This is the important
            # race fix for input-path -> output-path migration on conversion
            # completion.
            key = self._planned_target_storage_key(input_path)
            if move_running and key in move_paths:
                updater = getattr(move_thread, "update_planned_target", None)
                if not callable(updater) or not updater(key, target):
                    rejected.append(user_path_name(input_path))
                    continue

            self._state.planned_targets[key] = target
            self._log(f"📁 Ziel geändert: {user_path_name(input_path)} -> {target}", "info")
        return rejected

    def _change_planned_target(self, input_paths: tuple[str, ...]) -> None:
        rows = self._target_edit_rows(input_paths)
        if not rows:
            return
        replacements = self._choose_replacement_targets(rows)
        if not replacements:
            return
        # Do not reuse ``rows`` here: conversion completion can migrate the
        # target key while QFileDialog is open.
        rejected = self._apply_replacement_targets(input_paths, replacements)
        if len(rejected) < len(rows):
            self._refresh_queue_window()
        if rejected:
            preview = "\n".join(f"• {name}" for name in rejected[:8])
            more = f"\n… und {len(rejected) - 8} weitere" if len(rejected) > 8 else ""
            QMessageBox.information(
                self,
                "Ziel teilweise nicht geändert",
                "Für diese Datei(en) hat der eigentliche Verschiebevorgang bereits begonnen. "
                "Das Ziel wurde aus Transaktionssicherheitsgründen nicht mehr geändert:\n\n"
                f"{preview}{more}",
            )
