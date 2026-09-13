# -*- coding: utf-8 -*-
from __future__ import annotations

import traceback

from PyQt6.QtCore import QSettings

from ..core.settings import APP_NAME, APP_ORG, SET_KEY_MOVE_CONFLICT
from .move_lifecycle_helpers import format_move_eta, merge_restored_target_paths, retire_move_thread


class RegularMoveLifecycle:
    """Lifecycle eines abschließenden Move-Laufs nach der Konvertierung."""

    def __init__(
        self,
        *,
        state,
        ui,
        log,
        get_target_paths,
        finalize_run,
        set_start_enabled,
        set_queue_edit,
        refresh_queue,
        worker_factory,
        on_move_req,
    ) -> None:
        self._state = state
        self._ui = ui
        self._log = log
        self._get_target_paths = get_target_paths
        self._finalize_run = finalize_run
        self._set_start_enabled = set_start_enabled
        self._set_queue_edit = set_queue_edit
        self._refresh_queue = refresh_queue
        self._worker_factory = worker_factory
        self._on_move_req = on_move_req

    def start(self, files: list[str], finished_thread) -> None:
        try:
            self._prepare_ui(files)
            restored_context = self._restored_context(finished_thread)
            paths = merge_restored_target_paths(self._get_target_paths(), restored_context)
            conflict_mode = self._conflict_mode(restored_context)
            move_thread = self._create_thread(
                files,
                finished_thread=finished_thread,
                paths=paths,
                conflict_mode=conflict_mode,
                restored_context=restored_context,
            )
            self._wire_thread(move_thread, files, finished_thread)
            move_thread.start()
        except Exception:
            self._log("❌ Unbehandelte Ausnahme in start_move()", "error")
            self._log(traceback.format_exc(), "error")

    def _prepare_ui(self, files: list[str]) -> None:
        ui = self._ui
        self._log(f"📦 Verschiebe {len(files)} Datei(en) …")
        ui.file_bar.setValue(100)
        ui.file_bar.setFormat("✅ Konvertierung abgeschlossen")
        ui.eta_lbl.setText("")
        ui.progress_bar.setValue(0)
        ui.total_lbl.setText(f"Gesamt: Verschieben 0/{len(files)}")

    def _restored_context(self, finished_thread) -> dict:
        if finished_thread is not None:
            return {}
        return dict(getattr(self._state, "restored_move_context", {}) or {})

    @staticmethod
    def _conflict_mode(restored_context: dict) -> str:
        return str(restored_context.get("conflict_mode") or "") or QSettings(
            APP_ORG, APP_NAME
        ).value(SET_KEY_MOVE_CONFLICT, "skip", type=str)

    def _create_thread(
        self,
        files: list[str],
        *,
        finished_thread,
        paths: dict,
        conflict_mode: str,
        restored_context: dict,
    ):
        state = self._state
        state.incremental_move_active = False
        move_thread = self._worker_factory(
            files,
            tv_path=paths.get("tv") or None,
            anime_path=paths.get("anime") or None,
            filme_path=paths.get("film") or None,
            shutdown_getter=lambda: self._ui.shut_cb.isChecked(),
            planned_targets=dict(state.planned_targets),
            conflict_mode=conflict_mode,
            log_file_path=getattr(finished_thread, "log_file_path", None),
            sidecar_outputs_by_video=dict(state.sidecar_outputs_by_video),
            supersedes_journal_path=str(restored_context.get("journal_path") or ""),
            companion_resume_sources=dict(restored_context.get("companion_resume_sources") or {}),
        )
        state.move_thread = move_thread
        return move_thread

    def _wire_thread(self, move_thread, files: list[str], finished_thread) -> None:
        ui = self._ui
        move_thread.log_line.connect(self._log)
        move_thread.progress.connect(ui.progress_bar.setValue)
        move_thread.request_user.connect(self._on_move_req)
        move_thread.file_counted.connect(
            lambda done, total: ui.total_lbl.setText(f"Gesamt: Verschieben {done}/{total}")
        )
        move_thread.move_eta.connect(lambda eta_s: ui.eta_lbl.setText(format_move_eta(eta_s)))
        move_thread.finished.connect(
            lambda moved, shutdown, thread=move_thread: self._finish(
                thread,
                finished_thread=finished_thread,
                moved=moved,
                shutdown=shutdown,
            )
        )

        self._set_start_enabled(False)
        self._set_queue_edit(False)
        ui.abort_btn.setEnabled(True)
        ui.pause_btn.setEnabled(True)
        ui.pause_btn.setText("⏸ Pause")
        self._refresh_queue()

    def _finish(self, move_thread, *, finished_thread, moved: bool, shutdown: bool) -> None:
        try:
            state = self._state
            ui = self._ui
            aborted = bool(move_thread and getattr(move_thread, "abort_requested", False))
            move_log = getattr(move_thread, "_move_report_log", [])
            move_ok = getattr(move_thread, "ok_count", 0)
            move_errors = getattr(move_thread, "error_count", 0)
            ui.abort_btn.setEnabled(False)
            ui.eta_lbl.setText("")
            if aborted:
                self._log("⏹ Verschieben abgebrochen.", "warn")
            elif move_errors:
                self._log(
                    f"⚠️ Verschieben mit {move_errors} Fehler(n) beendet ({move_ok} OK).",
                    "warn",
                )
            else:
                self._log("✅ Verschoben." if moved else "ℹ️ Nichts verschoben.")

            move_log_path = getattr(move_thread, "log_file_path", None)
            if move_log_path and not getattr(finished_thread, "log_file_path", None):
                state.current_log_path = move_log_path
                ui.curlog_btn.setEnabled(True)

            user_declined = bool(move_thread and getattr(move_thread, "user_declined_shutdown", False))
            shutdown_handled = aborted or user_declined
            if state.move_thread is move_thread:
                state.move_thread = None
            retire_move_thread(state, move_thread)
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
            ui.pause_btn.setText("⏸ Pause")
            self._refresh_queue()
        except Exception:
            self._log("❌ Unbehandelte Ausnahme in _move_done()", "error")
            self._log(traceback.format_exc(), "error")
