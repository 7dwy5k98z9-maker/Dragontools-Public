# -*- coding: utf-8 -*-
"""
dragontools/gui/conversion_result_service.py

Ergebnisverarbeitung: pro-Datei-Callbacks und Run-Abschluss.

Vollständig vom owner-basierten Muster entkoppelt; alle Abhängigkeiten
werden per Dependency Injection übergeben.
"""
from __future__ import annotations

import time
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Callable



from ..core.run_summary import build_run_summary
from .conversion_session_state import ConversionSessionState

if TYPE_CHECKING:
    from .convert_widget_layout import ConvertWidgetUI


class ConversionResultService:
    """
    Verarbeitet Worker-Ergebnisse und koordiniert den Run-Abschluss.

    Verantwortlichkeiten:
      - on_file_result  – Slot für worker.file_result  (Status pro Datei)
      - on_file_progress – Slot für worker.file_progress (delegiert an Controller)
      - on_finished     – Slot für worker.finished     (Run-Abschluss)
      - finalize_run    – Zusammenfassung schreiben, Queue leeren, Shutdown-Frage
      - log_run_summary – Logger-API aufrufen

    Kein Zugriff auf »owner«; alle UI- und State-Abhängigkeiten injiziert.
    """

    def __init__(
        self,
        *,
        state: ConversionSessionState,
        ui: ConvertWidgetUI,
        log: Callable,
        start_move: Callable,          # (files: list[str], finished_thread) -> None
        set_start_enabled: Callable,   # (bool) -> None
        set_queue_edit: Callable,      # (bool) -> None
        refresh_queue: Callable,       # () -> None
        clear: Callable,               # () -> None
        confirm_shutdown: Callable,    # () -> None
        parent_widget=None,
        requeue_files: Callable[[list[str]], None] | None = None,
    ) -> None:
        self._state            = state
        self._ui               = ui
        self._log              = log
        self._start_move       = start_move
        self._set_start_enabled = set_start_enabled
        self._set_queue_edit   = set_queue_edit
        self._refresh_queue    = refresh_queue
        self._clear            = clear
        self._confirm_shutdown = confirm_shutdown
        self._parent_widget    = parent_widget
        self._requeue_files    = requeue_files
        self._on_file_progress_impl: Callable | None = None

    def set_file_progress_handler(self, handler: Callable) -> None:
        """Verbindet den file_progress-Handler nachträglich (nach Controller-Erzeugung)."""
        self._on_file_progress_impl = handler

    # ── Signal-Slots ────────────────────────────────────────────────

    def on_file_progress(self, path: str, pct: int, eta_s) -> None:
        """Slot für worker.file_progress – delegiert an ConversionController."""
        if self._on_file_progress_impl is not None:
            self._on_file_progress_impl(path, pct, eta_s)

    def on_file_result(self, input_path: str, output_path: str, status: str) -> None:
        """Slot für worker.file_result – aktualisiert State und List-Item-Text."""
        self._set_file_list_item_text(input_path, f"{status}  {Path(input_path).name}")
        state = self._state
        if status == "🧩":
            state.pending_postprocess_inputs.add(input_path)
            self._refresh_queue()
            return
        if status not in {"\u2705", "\u274c", "\u26a0\ufe0f", "\u23ed\ufe0f"}:
            self._refresh_queue()
            return

        state.pending_postprocess_inputs.discard(input_path)
        state.completed_inputs.add(input_path)
        self._record_terminal_result(input_path, output_path, status)
        self._record_journal_result(input_path, output_path, status)

        if input_path in state.pending_remove_paths:
            state.pending_remove_paths.discard(input_path)
            self._ui.file_list.remove_path(input_path)
            state.file_overrides.pop(input_path, None)
            state.planned_targets.pop(input_path, None)
            state.planned_targets.pop(output_path, None)
            self._log(
                f"\u23ed\ufe0f '{Path(input_path).name}' wurde nach Abschluss aus der Queue entfernt.",
                "info",
            )
            self._refresh_queue()
            return

        if status == "\u2705":
            blocked_inputs = set()
            replace_service = getattr(
                getattr(self._state.thread, "_replace_service", None),
                "blocked_move_inputs",
                None,
            )
            if replace_service is not None:
                blocked_inputs = set(replace_service)
            if input_path not in blocked_inputs:
                state.fertig.add(output_path)
                # Sidecar-Pfade (externe Untertitel) aus dem Worker-Thread lesen
                # und am State registrieren.  Beide Thread-Typen (ConverterThread
                # und DVRemuxThread) legen ihre Sidecars in _sidecar_outputs[input_path] ab.
                thread = self._state.thread
                sidecar_map: dict = getattr(thread, "_sidecar_outputs", {}) if thread else {}
                sidecars: list[str] = sidecar_map.get(input_path, [])
                state.sidecar_outputs_by_video[output_path] = sidecars
                self._update_result_sidecars(input_path, sidecars)
                postprocess_map: dict = getattr(thread, "_postprocess_outputs", {}) if thread else {}
                postprocess = [dict(item) for item in (postprocess_map.get(input_path, []) or [])]
                state.postprocess_outputs_by_input[input_path] = postprocess
                self._update_result_postprocess(input_path, postprocess)
            planned_target = state.planned_targets.get(input_path)
            if planned_target and output_path != input_path:
                override = state.file_overrides.pop(input_path, None)
                state.planned_targets[output_path] = planned_target
                state.planned_targets.pop(input_path, None)
                if override is not None:
                    state.file_overrides[output_path] = override

        self._refresh_queue()
        if state.finish_waiting_for_postprocess and not state.pending_postprocess_inputs:
            state.finish_waiting_for_postprocess = False
            self.on_finished()

    def on_finished(self) -> None:
        """Slot für worker.finished – koordiniert Run-Abschluss."""
        try:
            ui = self._ui
            ui.pause_btn.setEnabled(False)
            ui.abort_btn.setEnabled(False)
            ui.pause_btn.setText("\u23f8 Pause")
            if hasattr(ui.abort_btn, "setText"):
                ui.abort_btn.setText("\u274c Abbrechen")
            if hasattr(ui.abort_btn, "setToolTip"):
                ui.abort_btn.setToolTip("Aktiven Vorgang abbrechen")
            ui.file_lbl.setText("")
            ui.eta_lbl.setText("")
            self._refresh_queue()

            if self._state.pending_postprocess_inputs:
                if not self._state.finish_waiting_for_postprocess:
                    self._log(
                        "🧩 Warte auf abgeschlossenes Post-Processing, bevor verschoben wird.",
                        "info",
                    )
                self._state.finish_waiting_for_postprocess = True
                return
            self._state.finish_waiting_for_postprocess = False

            finished_thread = self._state.thread
            aborted = bool(finished_thread and getattr(finished_thread, "abort_requested", False))
            if aborted:
                self._log("\u23f9 Konvertierung abgebrochen.")
                if self._should_offer_move_after_abort(finished_thread):
                    move_files = list(self._state.fertig)
                    if self._confirm_move_after_abort(len(move_files)):
                        self._log(
                            f"\U0001f4e6 Abbruch: {len(move_files)} erfolgreich konvertierte Datei(en) "
                            "werden jetzt verschoben.",
                            "warn",
                        )
                        self._start_move(move_files, finished_thread)
                        self._state.thread = None
                        self._refresh_queue()
                        return
                    self._log(
                        "\u2139\ufe0f Abbruch: Erfolgreich konvertierte Datei(en) werden nicht verschoben.",
                        "info",
                    )
                    self.finalize_run(
                        finished_thread,
                        move_log=[],
                        did_shutdown=True,
                        move_ok=0,
                        move_errors=0,
                    )
                else:
                    self._finish_job_journal(finished_thread, status="aborted")
                    self._clear()
                self._state.thread = None
                self._set_start_enabled(True)
                self._set_queue_edit(True)
                self._refresh_queue()
                return

            ui.progress_bar.setValue(100)
            self._log("\u2705 Konvertierung abgeschlossen.")
            if ui.move_cb.isChecked() and self._state.fertig:
                self._start_move(list(self._state.fertig), finished_thread)
            else:
                self.finalize_run(finished_thread, move_log=[], move_ok=0, move_errors=0)
                self._set_start_enabled(True)
                self._set_queue_edit(True)

            self._state.thread = None
            self._refresh_queue()
        except Exception:
            self._log("\u274c Unbehandelte Ausnahme in on_finished()", "error")
            self._log(traceback.format_exc(), "error")

    # ── Run-Zusammenfassung ─────────────────────────────────────────

    def _should_offer_move_after_abort(self, finished_thread) -> bool:
        if not finished_thread or not getattr(finished_thread, "abort_requested", False):
            return False
        return bool(self._state.fertig)

    def _confirm_move_after_abort(self, count: int) -> bool:
        try:
            from PyQt6.QtWidgets import QMessageBox

            box = QMessageBox(self._parent_widget)
            box.setWindowTitle("Abbruch - Dateien verschieben?")
            box.setIcon(QMessageBox.Icon.Question)
            box.setText(
                f"{count} erfolgreich konvertierte Datei(en) wurden noch nicht verschoben."
            )
            box.setInformativeText("Sollen diese Dateien jetzt noch automatisch verschoben werden?")
            yes_btn = box.addButton("Ja, verschieben", QMessageBox.ButtonRole.YesRole)
            box.addButton("Nein", QMessageBox.ButtonRole.NoRole)
            box.setDefaultButton(yes_btn)
            box.exec()
            return box.clickedButton() is yes_btn
        except Exception as exc:
            self._log(f"Abbruch-Verschiebeabfrage konnte nicht angezeigt werden: {exc}", "warn")
            return False

    def finalize_run(
        self,
        finished_thread,
        move_log: list | None = None,
        did_shutdown: bool = False,
        move_ok: int = 0,
        move_errors: int = 0,
    ) -> None:
        """Schreibt die Zusammenfassung, leert die Queue und fragt ggf. nach Shutdown."""
        try:
            if self._state.summary_written:
                return
            self._state.summary_written = True
            total_move_log = list(getattr(self._state, "move_report_log", []) or [])
            total_move_log.extend(move_log or [])
            total_move_ok = int(getattr(self._state, "move_ok_count", 0) or 0) + int(move_ok or 0)
            total_move_errors = (
                int(getattr(self._state, "move_error_count", 0) or 0)
                + int(move_errors or 0)
            )
            self.log_run_summary(
                finished_thread,
                total_move_log,
                total_move_ok,
                total_move_errors,
            )
            shutdown_requested = bool(self._ui.shut_cb.isChecked())
            retry_files = []
            if shutdown_requested and not did_shutdown:
                self._log(
                    "ℹ️ Abschlussbericht wird wegen aktiviertem Herunterfahren nicht geöffnet.",
                    "info",
                )
            elif not shutdown_requested:
                self._show_replacement_reminders()
                retry_files = self._show_run_summary_dialog(
                    finished_thread,
                    move_ok=total_move_ok,
                    move_errors=total_move_errors,
                )
            self._finish_job_journal(
                finished_thread,
                status="aborted" if bool(getattr(finished_thread, "abort_requested", False)) else "completed",
            )
            self._clear()
            if retry_files and self._requeue_files:
                self._requeue_files(retry_files)
                self._log(
                    f"{len(retry_files)} Fehlerdatei(en) erneut in die Queue gelegt.",
                    "warn",
                )
            if retry_files:
                return
            if shutdown_requested and not did_shutdown:
                self._confirm_shutdown()
        except Exception:
            self._log("\u274c Unbehandelte Ausnahme in finalize_run()", "error")
            self._log(traceback.format_exc(), "error")

    def _show_replacement_reminders(self) -> None:
        try:
            from ..core.replacement_reminders import list_replacement_reminders
            from .replacement_reminder_dialog import show_pending_replacement_reminders

            before = list_replacement_reminders()
            before_ids = [str(item.get("id") or "") for item in before if item.get("id")]
            removed = show_pending_replacement_reminders(self._parent_widget)
            if removed:
                after_ids = {
                    str(item.get("id") or "")
                    for item in list_replacement_reminders()
                    if item.get("id")
                }
                removed_ids = [value for value in before_ids if value not in after_ids]
                ids_text = ", ".join(removed_ids) if removed_ids else f"{removed} Eintrag/Einträge"
                self._log(
                    f"✅ Ersetzungs-Erinnerung bestätigt und aus der Erinnerungsliste gelöscht: {ids_text}",
                    "info",
                )
        except Exception as exc:
            self._log(f"Ersetzungs-Erinnerungen konnten nicht angezeigt werden: {exc}", "warn")

    def log_run_summary(
        self,
        finished_thread,
        move_log: list,
        move_ok: int,
        move_errors: int,
    ) -> None:
        logger = getattr(finished_thread, "_logger", None) if finished_thread else None
        is_dv_remux = bool(
            finished_thread
            and finished_thread.__class__.__name__ == "DVRemuxThread"
        )
        if logger is not None and not is_dv_remux:
            total_before = getattr(finished_thread, "total_before", 0)
            total_after  = getattr(finished_thread, "total_after", 0)
            run_start    = getattr(finished_thread, "_run_start_ts", None)
            total_duration_s = time.time() - run_start if run_start else 0
            # Archivierungszähler aus dem ReplaceService des Threads lesen
            replace_svc = getattr(finished_thread, "_replace_service", None)
            archiviert = getattr(replace_svc, "archiviert", 0)
            logger.summary(
                ok=getattr(finished_thread, "erfolgreich", 0),
                errors=getattr(finished_thread, "fehlgeschlagen", 0),
                saved_bytes=total_before - total_after,
                total_duration_s=total_duration_s,
                total_before=total_before,
                total_after=total_after,
                move_log=move_log,
                start_ts=run_start,
                move_ok=move_ok,
                move_errors=move_errors,
                archiviert=archiviert,
            )
        elif logger is not None and is_dv_remux:
            # DV-Remux hat keine Konvertierungs-Stats (total_before/after etc.).
            # Nur Verschiebebericht und Verschoben-Zähler schreiben.
            logger.info("DV-Remux abgeschlossen.")
            logger.move_summary(move_log, move_ok, move_errors)

    # ── Helpers ─────────────────────────────────────────────────────

    def _record_terminal_result(self, input_path: str, output_path: str, status: str) -> None:
        if status not in {"\u2705", "\u274c", "\u26a0\ufe0f", "\u23ed\ufe0f"}:
            return
        status_key = {
            "\u2705": "ok",
            "\u274c": "error",
            "\u26a0\ufe0f": "error",
            "\u23ed\ufe0f": "skipped",
        }.get(status, "error")
        details = {}
        if status_key in {"error", "skipped"}:
            thread = self._state.thread
            detail_map: dict = getattr(thread, "_failure_details", {}) if thread else {}
            details = dict(detail_map.get(input_path, {}) or {})
        self._state.run_results[input_path] = {
            "input_path": input_path,
            "output_path": output_path if status_key == "ok" else "",
            "status": status_key,
            "sidecars": [],
            "postprocess": [],
            "message": str(details.get("message", "") or ""),
            "error_report": str(details.get("error_report", "") or ""),
            "pipeline": str(details.get("pipeline", "") or ""),
            "container": str(details.get("container", "") or ""),
            "strategy": str(details.get("strategy", "") or ""),
        }

    def _record_journal_result(self, input_path: str, output_path: str, status: str) -> None:
        journal = getattr(self._state, "job_journal", None)
        if journal is None:
            return
        row = self._state.run_results.get(input_path, {})
        message = str(row.get("message", "") or "")
        try:
            journal.finish_file(
                input_path,
                output_path=output_path if row.get("status") == "ok" else "",
                status=status,
                message=message,
            )
            current_paths = getattr(self._state, "job_journal_current_paths", set())
            current_paths.discard(input_path)
            self._state.job_journal_current_path = next(iter(current_paths), None)
        except Exception as exc:
            self._log(f"⚠️ Job-Journal konnte Ergebnis nicht speichern: {exc}", "warn")

    def _finish_job_journal(self, finished_thread, *, status: str) -> None:
        journal = getattr(self._state, "job_journal", None)
        if journal is None:
            return
        try:
            journal.finish_run(status=status)
        except Exception as exc:
            self._log(f"⚠️ Job-Journal konnte nicht finalisiert werden: {exc}", "warn")
        self._state.job_journal = None
        self._state.job_journal_current_path = None
        self._state.job_journal_current_paths.clear()

    def _update_result_sidecars(self, input_path: str, sidecars: list[str]) -> None:
        row = self._state.run_results.get(input_path)
        if row is not None:
            row["sidecars"] = list(sidecars or [])

    def _update_result_postprocess(self, input_path: str, postprocess: list[dict]) -> None:
        row = self._state.run_results.get(input_path)
        if row is not None:
            row["postprocess"] = [dict(item) for item in (postprocess or [])]

    def _build_run_summary(self, finished_thread, *, move_ok: int, move_errors: int) -> dict:
        replace_svc = getattr(finished_thread, "_replace_service", None) if finished_thread else None
        return build_run_summary(
            list(self._state.run_results.values()),
            total_before=getattr(finished_thread, "total_before", 0),
            total_after=getattr(finished_thread, "total_after", 0),
            move_ok=move_ok,
            move_errors=move_errors,
            archived=getattr(replace_svc, "archiviert", 0),
        )

    def _show_run_summary_dialog(self, finished_thread, *, move_ok: int, move_errors: int) -> list[str]:
        try:
            from .run_summary_dialog import RunSummaryDialog

            summary = self._build_run_summary(
                finished_thread,
                move_ok=move_ok,
                move_errors=move_errors,
            )
            dlg = RunSummaryDialog(summary, parent=self._parent_widget)
            dlg.exec()
            if dlg.action() == RunSummaryDialog.ACTION_REQUEUE_FAILED:
                return dlg.failed_inputs()
        except Exception:
            self._log("Abschlussdialog konnte nicht angezeigt werden.", "warn")
            self._log(traceback.format_exc(), "error")
        return []

    def _set_file_list_item_text(self, path: str, text: str) -> None:
        from .ui_helpers import set_file_list_item_text
        set_file_list_item_text(self._ui.file_list, path, text)
