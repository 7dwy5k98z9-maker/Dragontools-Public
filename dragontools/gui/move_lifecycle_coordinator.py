# -*- coding: utf-8 -*-
"""Lifecycle-Koordination für reguläre und inkrementelle MoveThreads."""
from __future__ import annotations

import traceback
from pathlib import Path
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QMessageBox
from ..core.settings import APP_ORG, APP_NAME, SET_KEY_MOVE_CONFLICT


class MoveLifecycleCoordinator:
    def __init__(self, *, state, ui, log, parent, get_target_paths, finalize_run, set_start_enabled, set_queue_edit, refresh_queue, worker_factory, on_move_req, set_file_text):
        self._state = state
        self._ui = ui
        self._log = log
        self._parent = parent
        self._get_target_paths = get_target_paths
        self._finalize_run = finalize_run
        self._set_start_enabled = set_start_enabled
        self._set_queue_edit = set_queue_edit
        self._refresh_queue = refresh_queue
        self._worker_factory = worker_factory
        self._on_move_req = on_move_req
        self._set_file_text = set_file_text

    def start_move(self, files: list[str], finished_thread) -> None:
            """Startet den MoveThread nach abgeschlossener Konvertierung."""
            try:
                ui    = self._ui
                state = self._state
                self._log(f"\U0001F4E6 Verschiebe {len(files)} Datei(en) \u2026")
                ui.file_bar.setValue(100)
                ui.file_bar.setFormat("\u2705 Konvertierung abgeschlossen")
                ui.eta_lbl.setText("")
                ui.progress_bar.setValue(0)
                ui.total_lbl.setText(f"Gesamt: Verschieben 0/{len(files)}")

                paths = self._get_target_paths()
                restored_context = (
                    dict(getattr(state, "restored_move_context", {}) or {})
                    if finished_thread is None
                    else {}
                )
                restored_target_paths = (
                    restored_context.get("target_paths")
                    if isinstance(restored_context.get("target_paths"), dict)
                    else {}
                )
                for key in ("tv", "anime", "film"):
                    value = str((restored_target_paths or {}).get(key) or "")
                    if value:
                        paths[key] = value
                _conflict_mode = str(restored_context.get("conflict_mode") or "") or QSettings(APP_ORG, APP_NAME).value(
                    SET_KEY_MOVE_CONFLICT, "skip", type=str
                )
                state.incremental_move_active = False
                move_thread = self._worker_factory(
                    files,
                    tv_path=paths.get("tv") or None,
                    anime_path=paths.get("anime") or None,
                    filme_path=paths.get("film") or None,
                    shutdown_getter=lambda: ui.shut_cb.isChecked(),
                    planned_targets=dict(state.planned_targets),
                    conflict_mode=_conflict_mode,
                    log_file_path=getattr(finished_thread, "log_file_path", None),
                    sidecar_outputs_by_video=dict(state.sidecar_outputs_by_video),
                    supersedes_journal_path=str(restored_context.get("journal_path") or ""),
                    companion_resume_sources=dict(restored_context.get("companion_resume_sources") or {}),
                )
                state.move_thread = move_thread
                move_thread.log_line.connect(self._log)
                move_thread.progress.connect(ui.progress_bar.setValue)
                move_thread.request_user.connect(self._on_move_req)

                _total_move_files = len(files)

                def _on_file_counted(done: int, total: int) -> None:
                    ui.total_lbl.setText(f"Gesamt: Verschieben {done}/{total}")

                move_thread.file_counted.connect(_on_file_counted)
                self._set_start_enabled(False)
                self._set_queue_edit(False)
                ui.abort_btn.setEnabled(True)
                ui.pause_btn.setEnabled(True)
                ui.pause_btn.setText("⏸ Pause")
                self._refresh_queue()

                def _on_move_eta(eta_s: float) -> None:
                    if eta_s < 0:
                        ui.eta_lbl.setText("")
                        return
                    if eta_s < 60:
                        txt = f"Verschieben \u2013 noch ca. {int(eta_s)} s"
                    elif eta_s < 3600:
                        m, s = divmod(int(eta_s), 60)
                        txt = f"Verschieben \u2013 noch ca. {m} min {s:02d} s"
                    else:
                        h, rem = divmod(int(eta_s), 3600)
                        m = rem // 60
                        txt = f"Verschieben \u2013 noch ca. {h} h {m:02d} min"
                    ui.eta_lbl.setText(txt)

                move_thread.move_eta.connect(_on_move_eta)

                def _move_done(moved, shutdown, finished_move_thread=move_thread) -> None:
                    try:
                        aborted = bool(
                            finished_move_thread and getattr(finished_move_thread, "abort_requested", False)
                        )
                        ui.abort_btn.setEnabled(False)
                        ui.eta_lbl.setText("")
                        if aborted:
                            self._log("\u23f9 Verschieben abgebrochen.", "warn")
                        else:
                            self._log("\u2705 Verschoben." if moved else "\u2139\ufe0f Nichts verschoben.")

                        move_log    = getattr(finished_move_thread, "_move_report_log", [])
                        move_ok     = getattr(finished_move_thread, "ok_count", 0)
                        move_errors = getattr(finished_move_thread, "error_count", 0)

                        # Log-Button aktivieren – bei Move-Only gibt es keinen
                        # finished_thread, daher Log-Pfad direkt vom MoveThread holen
                        move_log_path = getattr(finished_move_thread, "log_file_path", None)
                        if move_log_path and not getattr(finished_thread, "log_file_path", None):
                            self._state.current_log_path = move_log_path
                            ui.curlog_btn.setEnabled(True)
                        # shutdown als "erledigt" markieren wenn:
                        #   • MoveThread hat selbst heruntergefahren (shutdown=True)
                        #   • Nutzer hat Countdown-Dialog aktiv abgelehnt (kein zweiter Dialog)
                        #   • Abgebrochen (kein Shutdown nach Abbruch)
                        user_declined = bool(
                            finished_move_thread and getattr(finished_move_thread, "user_declined_shutdown", False)
                        )
                        shutdown_handled = aborted or user_declined
                        if state.move_thread is finished_move_thread:
                            state.move_thread = None
                        self.retire_move_thread(finished_move_thread)
                        state.restored_move_context.clear()
                        self._finalize_run(
                            finished_thread,
                            move_log=move_log,
                            did_shutdown=shutdown or shutdown_handled,
                            move_ok=move_ok,
                            move_errors=move_errors,
                        )
                        self._set_start_enabled(True)
                        self._set_queue_edit(True)
                        ui.pause_btn.setEnabled(False)
                        ui.pause_btn.setText("\u23f8 Pause")
                        self._refresh_queue()
                    except Exception:
                        self._log("\u274c Unbehandelte Ausnahme in _move_done()", "error")
                        self._log(traceback.format_exc(), "error")

                move_thread.finished.connect(_move_done)
                move_thread.start()
            except Exception:
                self._log("\u274c Unbehandelte Ausnahme in start_move()", "error")
                self._log(traceback.format_exc(), "error")

    def move_finished_now(self) -> None:
            """Verschiebt bereits erfolgreich konvertierte Dateien während eines laufenden Runs."""
            try:
                if self._state.move_thread and self._state.move_thread.isRunning():
                    QMessageBox.information(
                        self._parent,
                        "Verschieben läuft",
                        "Es läuft bereits ein Verschiebevorgang.",
                    )
                    return

                files = self.collect_finished_move_candidates()
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
                if reply != QMessageBox.StandardButton.Yes:
                    return

                self.start_incremental_move(files)
            except Exception:
                self._log("❌ Unbehandelte Ausnahme in move_finished_now()", "error")
                self._log(traceback.format_exc(), "error")

    def collect_finished_move_candidates(self) -> list[str]:
            files: list[str] = []
            missing: list[str] = []
            for path in sorted(self._state.fertig):
                if not path:
                    continue
                if Path(path).exists():
                    files.append(path)
                else:
                    missing.append(path)

            for path in missing:
                self._state.fertig.discard(path)
                self._state.sidecar_outputs_by_video.pop(path, None)
                self._log(
                    f"⚠️ Fertige Datei nicht mehr gefunden, aus Zwischenverschieben entfernt: {Path(path).name}",
                    "warn",
                )
            return files

    def start_incremental_move(self, files: list[str]) -> None:
            ui = self._ui
            state = self._state
            conversion_thread = state.thread
            if not (conversion_thread and conversion_thread.isRunning()):
                self._log("ℹ️ Zwischenverschieben wurde übersprungen: Es läuft keine Konvertierung.", "info")
                self._refresh_queue()
                return
            paths = self._get_target_paths()
            conflict_mode = QSettings(APP_ORG, APP_NAME).value(
                SET_KEY_MOVE_CONFLICT, "skip", type=str
            )
            log_file_path = (
                getattr(conversion_thread, "log_file_path", None)
                or state.current_log_path
                or None
            )
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
                lambda done, total: self._log(
                    f"📦 Zwischenverschieben: {done}/{total}",
                    "info",
                )
            )

            self._ui.move_finished_btn.setEnabled(False)
            self._refresh_queue()

            def _move_done(_moved, _shutdown, finished_move_thread=move_thread) -> None:
                self.finish_incremental_move(finished_move_thread)

            move_thread.finished.connect(_move_done)
            move_thread.start()

    def finish_incremental_move(self, move_thread=None) -> None:
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

                moved_sources = self.successful_video_sources(move_log)
                for output_path in moved_sources:
                    state.fertig.discard(output_path)
                    state.sidecar_outputs_by_video.pop(output_path, None)
                    state.planned_targets.pop(output_path, None)
                    for input_path in self.input_paths_for_output(output_path):
                        self.set_file_list_item_text(
                            input_path,
                            f"📦 Verschoben  {Path(input_path).name}",
                        )

                state.incremental_move_active = False
                if state.move_thread is move_thread:
                    state.move_thread = None
                self.retire_move_thread(move_thread)
                if move_errors:
                    self._log(
                        f"⚠️ Zwischenverschieben abgeschlossen: {move_ok} OK / {move_errors} Fehler.",
                        "warn",
                    )
                else:
                    self._log(
                        f"✅ Zwischenverschieben abgeschlossen: {move_ok} Datei(en) verschoben.",
                        "info",
                    )

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
                self.retire_move_thread(move_thread)
                self._log("❌ Unbehandelte Ausnahme in _finish_incremental_move()", "error")
                self._log(traceback.format_exc(), "error")
                self._refresh_queue()

    def retire_move_thread(self, move_thread) -> None:
            if move_thread is None:
                return
            retired = getattr(self._state, "retired_move_threads", None)
            if retired is None:
                return
            if move_thread not in retired:
                retired.append(move_thread)
            del retired[:-8]

    def successful_video_sources(self, move_log: list) -> set[str]:
            moved: set[str] = set()
            for entry in move_log or []:
                if not isinstance(entry, dict):
                    continue
                if entry.get("kind", "video") != "video":
                    continue
                if not entry.get("ok"):
                    continue
                src = str(entry.get("source_path") or "")
                if src:
                    moved.add(src)
            return moved

    def input_paths_for_output(self, output_path: str) -> list[str]:
            inputs: list[str] = []
            for input_path, result in self._state.run_results.items():
                if result.get("output_path") == output_path:
                    inputs.append(input_path)
            if not inputs and output_path:
                inputs.append(output_path)
            return inputs

    def set_file_list_item_text(self, path: str, text: str) -> None:
        self._set_file_text(path, text)
