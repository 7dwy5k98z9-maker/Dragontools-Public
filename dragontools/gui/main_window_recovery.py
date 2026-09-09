# -*- coding: utf-8 -*-
"""Recovery-/Resume-Orchestrierung des MainWindow."""
from __future__ import annotations

import logging

from PyQt6.QtWidgets import QMessageBox


_LOG = logging.getLogger(__name__)


class MainWindowRecoveryMixin:
    """Kapselt Job-/Move-Journal-Recovery und Replacement-Reminder."""

    def _maybe_show_recovery_journals(self) -> None:
        """Fuehrt Pfad-Recovery aus und zeigt Wiederherstellungsdialoge nacheinander."""
        _recover_replace_transactions(self)
        _recover_sidecar_transactions(self)
        self._show_unfinished_job_journal(show_empty_message=False, quiet_errors=True)
        self._show_unfinished_move_journal(show_empty_message=False, quiet_errors=True)

    def _maybe_show_unfinished_job_journal(self) -> None:
        self._show_unfinished_job_journal(show_empty_message=False, quiet_errors=True)

    def _show_unfinished_move_journal(
        self,
        *,
        show_empty_message: bool,
        quiet_errors: bool,
    ) -> None:
        try:
            from ..core.move_journal import (
                archive_active_move_journal,
                read_active_move_journal,
                recover_active_move_backups,
            )
            from .move_resume_dialog import MoveResumeDialog

            recovery = recover_active_move_backups()
            restored = int(recovery.get("restored", 0) or 0)
            completed = int(recovery.get("completed", 0) or 0)
            cleaned = int(recovery.get("cleaned", 0) or 0)
            if restored or completed or cleaned:
                parts = []
                if restored:
                    parts.append(f"{restored} alte Zieldatei(en) wiederhergestellt")
                if completed:
                    parts.append(f"{completed} Datei(en) nach Crash als abgeschlossen erkannt")
                if cleaned:
                    parts.append(f"{cleaned} temporäre Backup(s) bereinigt")
                self.statusBar().showMessage(
                    "🛡️ Move-Journal: " + ", ".join(parts) + ".",
                    9000,
                )

            data = read_active_move_journal()
            if not data:
                if show_empty_message:
                    QMessageBox.information(
                        self,
                        "Move-Wiederaufnahme",
                        "Es ist aktuell keine offene Verschiebequeue vorhanden.",
                    )
                return

            dlg = MoveResumeDialog(data, self)
            dlg.exec()
            action = dlg.action()
            if action == MoveResumeDialog.ACTION_LOAD:
                plan = dlg.resume_plan()
                result = self._restore_move_resume_plan(plan)
                QMessageBox.information(
                    self,
                    "Verschiebequeue vorbereitet",
                    "Die offenen Dateien wurden in die Warteschlange geladen.\n\n"
                    f"Geladen: {result.get('added', 0)}\n"
                    f"Bereits vorhanden: {result.get('duplicate', 0)}\n"
                    f"Nicht gefunden: {result.get('missing', 0)}\n"
                    f"Ungültig: {result.get('invalid', 0)}\n\n"
                    "Bitte die Queue prüfen und anschließend 'Nur verschieben' verwenden. "
                    "Das Move-Journal bleibt bis zum erneuten Verschiebeversuch erhalten.",
                )
                return
            if action == MoveResumeDialog.ACTION_ARCHIVE:
                archive_active_move_journal(
                    status="ignored",
                    journal_path=data.get("_journal_path"),
                )
                QMessageBox.information(
                    self,
                    "Move-Journal archiviert",
                    "Das unvollständige Move-Journal wurde archiviert. "
                    "Beim nächsten Start wird es nicht erneut gemeldet.",
                )
        except Exception as exc:
            _LOG.warning("Move-Wiederaufnahme konnte nicht geprüft werden: %s", exc, exc_info=True)
            if not quiet_errors:
                QMessageBox.warning(
                    self,
                    "Move-Wiederaufnahme",
                    f"Die offene Verschiebequeue konnte nicht geprüft werden:\n{exc}",
                )

    def _maybe_show_replacement_reminders(self) -> None:
        try:
            from .replacement_reminder_dialog import show_pending_replacement_reminders

            show_pending_replacement_reminders(self)
        except Exception as exc:
            # GUI-Startup-Boundary: Reminder dürfen den Programmstart nicht blockieren,
            # der Fehler muss aber diagnostizierbar bleiben.
            _LOG.warning("Replacement-Reminder konnten nicht angezeigt werden: %s", exc, exc_info=True)

    def _open_unfinished_job_journal(self) -> None:
        self._show_unfinished_job_journal(show_empty_message=True, quiet_errors=False)

    def _open_unfinished_move_journal(self) -> None:
        self._show_unfinished_move_journal(show_empty_message=True, quiet_errors=False)

    def _show_unfinished_job_journal(
        self,
        *,
        show_empty_message: bool,
        quiet_errors: bool,
    ) -> None:
        try:
            from ..core.job_journal import archive_active_job_journal, read_active_job_journal
            from .job_resume_dialog import JobResumeDialog

            data = read_active_job_journal()
            if not data:
                if show_empty_message:
                    QMessageBox.information(
                        self,
                        "Job-Wiederaufnahme",
                        "Es ist aktuell keine offene Restqueue vorhanden.",
                    )
                return
            dlg = JobResumeDialog(data, self)
            dlg.exec()
            action = dlg.action()
            if action == JobResumeDialog.ACTION_LOAD:
                plan = dlg.resume_plan()
                result = self._restore_job_resume_plan(plan)
                archive_active_job_journal(
                    status="restored_to_queue",
                    journal_path=data.get("_journal_path"),
                )
                QMessageBox.information(
                    self,
                    "Job-Wiederaufnahme vorbereitet",
                    "Die Restqueue wurde vorbereitet.\n\n"
                    f"Geladen: {result.get('added', 0)}\n"
                    f"Bereits vorhanden: {result.get('duplicate', 0)}\n"
                    f"Nicht gefunden: {result.get('missing', 0)}\n"
                    f"Ungültig: {result.get('invalid', 0)}\n\n"
                    "Bitte prüfe die Warteschlange und starte die Konvertierung danach manuell.",
                )
                return
            if action == JobResumeDialog.ACTION_ARCHIVE:
                archive_active_job_journal(
                    status="ignored",
                    journal_path=data.get("_journal_path"),
                )
                QMessageBox.information(
                    self,
                    "Job-Journal archiviert",
                    "Das unvollständige Job-Journal wurde archiviert. "
                    "Beim nächsten Start wird es nicht erneut gemeldet.",
                )
        except Exception as exc:
            _LOG.warning("Job-Wiederaufnahme konnte nicht geprüft werden: %s", exc, exc_info=True)
            if not quiet_errors:
                QMessageBox.warning(
                    self,
                    "Job-Wiederaufnahme",
                    f"Die offene Restqueue konnte nicht geprüft werden:\n{exc}",
                )

    def _restore_move_resume_plan(self, plan: dict) -> dict[str, int]:
        files = [str(path) for path in plan.get("files", []) if str(path or "")]
        codec = self._settings.value("defaults/codec", "h265", type=str)
        if codec not in {"h265", "h264", "av1"}:
            codec = "h265"
        widget = self._ensure_converter_widget(codec)
        if widget is None or not hasattr(widget, "restore_job_files"):
            QMessageBox.warning(
                self,
                "Move-Wiederaufnahme nicht möglich",
                "Ein Konverter-Tab zum Laden der Verschiebequeue konnte nicht geöffnet werden.",
            )
            return {"added": 0, "missing": 0, "duplicate": 0, "invalid": len(files)}

        result = widget.restore_job_files(
            files,
            context="move",
            planned_targets=plan.get("planned_targets") or {},
            sidecar_outputs_by_video=plan.get("sidecar_outputs_by_video") or {},
            target_paths=plan.get("target_paths") or {},
            conflict_mode=str(plan.get("conflict_mode") or ""),
            journal_path=str(plan.get("journal_path") or ""),
            companion_resume_sources=plan.get("companion_resume_sources") or {},
        )
        self.statusBar().showMessage(
            f"🚚 Move-Wiederaufnahme: {result.get('added', 0)} Datei(en) geladen – anschließend 'Nur verschieben' verwenden.",
            9000,
        )
        return result

    def _restore_job_resume_plan(self, plan: dict) -> dict[str, int]:
        files = [str(path) for path in plan.get("files", []) if str(path or "")]
        codec = str(plan.get("codec") or "h265").lower()
        if codec not in {"h265", "h264", "av1"}:
            codec = "h265"
        widget = self._ensure_converter_widget(codec)
        if widget is None or not hasattr(widget, "restore_job_files"):
            QMessageBox.warning(
                self,
                "Wiederaufnahme nicht möglich",
                "Der passende Konverter-Tab konnte nicht geöffnet werden.",
            )
            return {"added": 0, "missing": 0, "duplicate": 0, "invalid": len(files)}

        result = widget.restore_job_files(files)
        mode = str(plan.get("mode") or "")
        hint = "Konvertierung"
        if mode == "dv_remux":
            hint = "DV-Remux"
        self.statusBar().showMessage(
            f"🔁 Job-Wiederaufnahme: {result.get('added', 0)} Datei(en) für {hint} geladen.",
            7000,
        )
        return result

def _recover_replace_transactions(window) -> None:
    """Best-effort Startup-Recovery fuer unterbrochene Converter-Replaces."""
    try:
        from ..core.replace_journal import recover_active_replace_journals

        recovery = recover_active_replace_journals()
        repaired = int(recovery.get("restored", 0) or 0) + int(recovery.get("cleaned_sources", 0) or 0)
        if repaired:
            window.statusBar().showMessage(
                f"🛡️ Replace-Recovery: {repaired} unterbrochene Transaktion(en) bereinigt.",
                9000,
            )
    except Exception as exc:
        _LOG.warning("Replace-Recovery konnte nicht ausgeführt werden: %s", exc, exc_info=True)



def _recover_sidecar_transactions(window) -> None:
    """Best-effort Startup-Recovery fuer unterbrochene Sidecar-Commits."""
    try:
        from ..core.sidecar_journal import recover_active_sidecar_journals

        recovery = recover_active_sidecar_journals()
        repaired = int(recovery.get("rolled_back", 0) or 0) + int(recovery.get("completed", 0) or 0)
        pending = int(recovery.get("pending", 0) or 0)
        if repaired:
            window.statusBar().showMessage(
                f"🛡️ Sidecar-Recovery: {repaired} unterbrochene Transaktion(en) bereinigt.",
                9000,
            )
        if pending:
            _LOG.warning("Sidecar-Recovery: %s Transaktion(en) bleiben manuell zu pruefen.", pending)
    except Exception as exc:
        _LOG.warning("Sidecar-Recovery konnte nicht ausgeführt werden: %s", exc, exc_info=True)
