# -*- coding: utf-8 -*-
"""Worker-Ende, Abbruch und Move-Entscheidung für Konvertierungsläufe."""
from __future__ import annotations

import traceback


class ConversionResultFinishMixin:
    """Koordiniert das Ende des Workers bis zur Übergabe an Move/Finalizer."""

    def on_finished(self) -> None:
        try:
            ui = self._ui
            ui.pause_btn.setEnabled(False)
            ui.abort_btn.setEnabled(False)
            ui.pause_btn.setText("⏸ Pause")
            if hasattr(ui.abort_btn, "setText"):
                ui.abort_btn.setText("❌ Abbrechen")
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
            aborted = bool(
                finished_thread and getattr(finished_thread, "abort_requested", False)
            )
            if aborted:
                self._handle_aborted_run(finished_thread)
                return

            ui.progress_bar.setValue(100)
            self._log("✅ Konvertierung abgeschlossen.")
            if ui.move_cb.isChecked() and self._state.fertig:
                self._start_move(list(self._state.fertig), finished_thread)
            else:
                self.finalize_run(finished_thread, move_log=[], move_ok=0, move_errors=0)
                self._set_start_enabled(True)
                self._set_queue_edit(True)

            self._state.thread = None
            self._refresh_queue()
        except Exception:
            self._log("❌ Unbehandelte Ausnahme in on_finished()", "error")
            self._log(traceback.format_exc(), "error")

    def _handle_aborted_run(self, finished_thread) -> None:
        self._log("⏹ Konvertierung abgebrochen.")
        if self._should_offer_move_after_abort(finished_thread):
            move_files = list(self._state.fertig)
            if self._confirm_move_after_abort(len(move_files)):
                self._log(
                    f"📦 Abbruch: {len(move_files)} erfolgreich konvertierte Datei(en) "
                    "werden jetzt verschoben.",
                    "warn",
                )
                self._start_move(move_files, finished_thread)
                self._state.thread = None
                self._refresh_queue()
                return
            self._log(
                "ℹ️ Abbruch: Erfolgreich konvertierte Datei(en) werden nicht verschoben.",
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
            box.setInformativeText(
                "Sollen diese Dateien jetzt noch automatisch verschoben werden?"
            )
            yes_btn = box.addButton("Ja, verschieben", QMessageBox.ButtonRole.YesRole)
            box.addButton("Nein", QMessageBox.ButtonRole.NoRole)
            box.setDefaultButton(yes_btn)
            box.exec()
            return box.clickedButton() is yes_btn
        except Exception as exc:
            self._log(
                f"Abbruch-Verschiebeabfrage konnte nicht angezeigt werden: {exc}",
                "warn",
            )
            return False
