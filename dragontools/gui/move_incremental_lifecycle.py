# -*- coding: utf-8 -*-
from __future__ import annotations

import traceback
from pathlib import Path

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QMessageBox

from ..core.settings import APP_NAME, APP_ORG, SET_KEY_MOVE_CONFLICT
from .move_lifecycle_helpers import (
    input_paths_for_output,
    retire_move_thread,
    successful_video_sources,
)


class IncrementalMoveLifecycle:
    """Zwischenverschieben bereits fertiger Outputs während eines laufenden Runs."""

    def __init__(
        self,
        *,
        state,
        ui,
        log,
        parent,
        get_target_paths,
        set_start_enabled,
        set_queue_edit,
        refresh_queue,
        worker_factory,
        on_move_req,
        set_file_text,
    ) -> None:
        self._state = state
        self._ui = ui
        self._log = log
        self._parent = parent
        self._get_target_paths = get_target_paths
        self._set_start_enabled = set_start_enabled
        self._set_queue_edit = set_queue_edit
        self._refresh_queue = refresh_queue
        self._worker_factory = worker_factory
        self._on_move_req = on_move_req
        self._set_file_text = set_file_text

    def prompt_and_start(self) -> None:
        try:
            if self._state.move_thread and self._state.move_thread.isRunning():
                QMessageBox.information(self._parent, "Verschieben läuft", "Es läuft bereits ein Verschiebevorgang.")
                return

            files = self.collect_candidates()
            if not files:
                QMessageBox.information(
                    self._parent,
                    "Keine fertigen Dateien",
                    "Aktuell gibt es keine erfolgreich konvertierten Dateien, die verschoben werden können.",
                )
                self._refresh_queue()
                return

            reply = QMessageBox.question(
                self._parent,
                "Fertige Dateien verschieben?",
                f"Es werden {len(files)} bereits erfolgreich konvertierte Datei(en) verschoben.\n\n"
                "Die aktuell laufende Datei wird nicht berührt.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.start(files)
        except Exception:
            self._log("❌ Unbehandelte Ausnahme in move_finished_now()", "error")
            self._log(traceback.format_exc(), "error")

    def collect_candidates(self) -> list[str]:
        files: list[str] = []
        missing: list[str] = []
        for path in sorted(self._state.fertig):
            if not path:
                continue
            (files if Path(path).exists() else missing).append(path)

        for path in missing:
            self._state.fertig.discard(path)
            self._state.sidecar_outputs_by_video.pop(path, None)
            self._log(
                f"⚠️ Fertige Datei nicht mehr gefunden, aus Zwischenverschieben entfernt: {Path(path).name}",
                "warn",
            )
        return files

    def start(self, files: list[str]) -> None:
        state = self._state
        ui = self._ui
        conversion_thread = state.thread
        if not (conversion_thread and conversion_thread.isRunning()):
            self._log("ℹ️ Zwischenverschieben wurde übersprungen: Es läuft keine Konvertierung.", "info")
            self._refresh_queue()
            return

        paths = self._get_target_paths()
        conflict_mode = QSettings(APP_ORG, APP_NAME).value(SET_KEY_MOVE_CONFLICT, "skip", type=str)
        log_file_path = getattr(conversion_thread, "log_file_path", None) or state.current_log_path or None
        state.incremental_move_active = True
        self._log(f"📦 Zwischenverschieben: {len(files)} fertige Datei(en) …", "info")
        move_thread = self._worker_factory(
            files,
            tv_path=paths.get("tv") or None,
            anime_path=paths.get("anime") or None,
            filme_path=paths.get("film") or None,
            shutdown_getter=lambda: False,
            planned_targets=dict(state.planned_targets),
            all_video_files=list(getattr(ui.file_list, "get_paths", lambda: [])()),
            conflict_mode=conflict_mode,
            log_file_path=log_file_path,
            sidecar_outputs_by_video=dict(state.sidecar_outputs_by_video),
        )
        state.move_thread = move_thread
        move_thread.log_line.connect(self._log)
        move_thread.request_user.connect(self._on_move_req)
        move_thread.file_counted.connect(
            lambda done, total: self._log(f"📦 Zwischenverschieben: {done}/{total}", "info")
        )
        ui.move_finished_btn.setEnabled(False)
        self._refresh_queue()
        move_thread.finished.connect(lambda *_args, thread=move_thread: self.finish(thread))
        move_thread.start()

    def finish(self, move_thread=None) -> None:
        try:
            state = self._state
            ui = self._ui
            move_thread = move_thread or state.move_thread
            move_log = list(getattr(move_thread, "_move_report_log", []) or [])
            move_ok = int(getattr(move_thread, "ok_count", 0) or 0)
            move_errors = int(getattr(move_thread, "error_count", 0) or 0)

            state.move_report_log.extend(move_log)
            state.move_ok_count += move_ok
            state.move_error_count += move_errors
            self._consume_moved_outputs(move_log)

            state.incremental_move_active = False
            if state.move_thread is move_thread:
                state.move_thread = None
            retire_move_thread(state, move_thread)
            self._log_finish(move_ok, move_errors)

            conversion_running = bool(state.thread and state.thread.isRunning())
            self._set_queue_edit(True)
            self._set_start_enabled(not conversion_running)
            if not conversion_running:
                ui.abort_btn.setEnabled(False)
                ui.pause_btn.setEnabled(False)
                ui.pause_btn.setText("⏸ Pause")
            self._refresh_queue()
        except Exception:
            self._state.incremental_move_active = False
            if self._state.move_thread is move_thread:
                self._state.move_thread = None
            retire_move_thread(self._state, move_thread)
            self._log("❌ Unbehandelte Ausnahme in _finish_incremental_move()", "error")
            self._log(traceback.format_exc(), "error")
            self._refresh_queue()

    def _consume_moved_outputs(self, move_log: list) -> None:
        state = self._state
        for output_path in successful_video_sources(move_log):
            state.fertig.discard(output_path)
            state.sidecar_outputs_by_video.pop(output_path, None)
            state.planned_targets.pop(output_path, None)
            for input_path in input_paths_for_output(state.run_results, output_path):
                self._set_file_text(input_path, f"📦 Verschoben  {Path(input_path).name}")

    def _log_finish(self, move_ok: int, move_errors: int) -> None:
        if move_errors:
            self._log(f"⚠️ Zwischenverschieben abgeschlossen: {move_ok} OK / {move_errors} Fehler.", "warn")
        else:
            self._log(f"✅ Zwischenverschieben abgeschlossen: {move_ok} Datei(en) verschoben.", "info")
