# -*- coding: utf-8 -*-
"""Preflight-Workflow: Dialogstart, Nachstart-Preflight und Bericht."""
from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QDialog
from ..core.settings import APP_ORG, APP_NAME, SET_KEY_MOVE_CONFLICT


class MovePreflightWorkflow:
    def __init__(self, *, state, ui, log, parent, get_target_paths, remove_queued_files=None, rows_builder_getter=None):
        self._state = state
        self._ui = ui
        self._log = log
        self._parent = parent
        self._get_target_paths = get_target_paths
        self._remove_queued_files = remove_queued_files
        self._rows_builder_getter = rows_builder_getter or (lambda: None)

    @property
    def _preflight_rows_builder(self):
        return self._rows_builder_getter()

    def run_if_needed(self, files: list[str]) -> bool:
            """
            Zeigt den Preflight-Dialog wenn »Verschieben« aktiv ist.
            Gibt True zurück wenn der Run fortgesetzt werden soll.
            """
            if not self._ui.move_cb.isChecked():
                self._state.planned_targets.clear()
                return True
            from .preflight_dialog import PreFlightDialog
            paths = self._get_target_paths()
            dlg = PreFlightDialog(
                files,
                tv_path=paths.get("tv") or None,
                anime_path=paths.get("anime") or None,
                filme_path=paths.get("film") or None,
                parent=self._parent,
            )
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return False
            planned_targets = dlg.get_planned_targets()
            self._state.planned_targets = planned_targets
            if dlg.should_save_report():
                self.save_report(
                    files,
                    planned_targets,
                    paths,
                    title="Preflight-Bericht",
                )
            return True

    def maybe_for_new_files(self, added: list[str]) -> None:
            """Preflight für Dateien, die während eines laufenden Runs hinzugefügt wurden."""
            state = self._state
            thread = state.thread
            if not thread or not thread.isRunning():
                return
            if getattr(thread, "abort_requested", False):
                return
            if not self._ui.move_cb.isChecked():
                return

            needs_preflight = [p for p in added if p not in state.planned_targets]
            if not needs_preflight:
                return

            try:
                from .preflight_dialog import PreFlightDialog
                paths = self._get_target_paths()
                dlg = PreFlightDialog(
                    needs_preflight,
                    tv_path=paths.get("tv") or None,
                    anime_path=paths.get("anime") or None,
                    filme_path=paths.get("film") or None,
                    parent=self._parent,
                )
                dlg.setWindowTitle("Zielordner festlegen - neu hinzugef\u00fcgte Dateien")
                if dlg.exec() != QDialog.DialogCode.Accepted:
                    # Preflight abgebrochen → neu hinzugefügte Dateien aus Queue entfernen
                    if needs_preflight and self._remove_queued_files:
                        try:
                            self._remove_queued_files(needs_preflight)
                            self._log(
                                "⚠️ Preflight abgebrochen: neu hinzugefügte Datei(en) "
                                "wurden aus der Queue entfernt.",
                                "warn",
                            )
                        except Exception as exc:
                            self._log(
                                f"Fehler beim Entfernen aus Queue nach Preflight-Abbruch: {exc}",
                                "warn",
                            )
                    return
                new_targets = dlg.get_planned_targets()
                for path, target in new_targets.items():
                    if path not in state.planned_targets:
                        state.planned_targets[path] = target
                if dlg.should_save_report():
                    self.save_report(
                        needs_preflight,
                        new_targets,
                        paths,
                        title="Preflight-Bericht - nachträglich hinzugefügt",
                    )
                self._log(
                    f"\u270f\ufe0f Preflight: {len(new_targets)} Ziel(e) f\u00fcr nachtr\u00e4glich "
                    f"hinzugef\u00fcgte Datei(en) gesetzt."
                )
            except Exception:
                self._log("\u274c Fehler im Nachstart-Preflight", "error")
                self._log(traceback.format_exc(), "error")

    def save_report(
            self,
            files: list[str],
            planned_targets: dict[str, Any],
            target_paths: dict[str, str | None],
            *,
            title: str,
        ) -> Path | None:
            rows = None
            rows_builder = self._preflight_rows_builder
            if callable(rows_builder):
                try:
                    rows = rows_builder(files, planned_targets)
                except Exception as exc:
                    self._log(f"⚠️ Preflight-Bericht: Regelvorschau konnte nicht erstellt werden: {exc}", "warn")

            try:
                from ..core.preflight_report import write_preflight_report

                conflict_mode = QSettings(APP_ORG, APP_NAME).value(
                    SET_KEY_MOVE_CONFLICT, "skip", type=str
                )
                report_path = write_preflight_report(
                    files,
                    planned_targets=planned_targets,
                    target_paths=target_paths,
                    rows=rows,
                    settings_summary={
                        "Verschieben": "aktiv",
                        "Konfliktverhalten": conflict_mode,
                    },
                    title=title,
                )
                self._log(f"📋 Preflight-Bericht gespeichert: {report_path}")
                return report_path
            except Exception as exc:
                self._log(f"⚠️ Preflight-Bericht konnte nicht gespeichert werden: {exc}", "warn")
                return None
