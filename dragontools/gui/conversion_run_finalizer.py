# -*- coding: utf-8 -*-
"""Run-Zusammenfassung, Journalabschluss und Shutdown-Nachlauf."""
from __future__ import annotations

import logging
import time
import traceback

from ..core.run_summary import build_run_summary
from .conversion_run_reporting import RunCompletionReport, report_completion, notify_completion, notify_finalization_error


_LOG = logging.getLogger(__name__)


def _safe_log(callback, message: str, level: str) -> None:
    """Best-effort diagnostic logging that cannot break terminal cleanup."""
    try:
        callback(message, level)
    except Exception as exc:
        _LOG.error(
            "DragonTools-Logger ist während der Run-Finalisierung ausgefallen: %s",
            exc,
            exc_info=True,
        )


class ConversionRunFinalizerMixin:
    """Finalisiert einen kompletten Run nach Konvertierung und optionalem Move."""

    def finalize_run(
        self,
        finished_thread,
        move_log: list | None = None,
        did_shutdown: bool = False,
        move_ok: int = 0,
        move_errors: int = 0,
    ) -> None:
        if self._state.summary_written or bool(getattr(self._state, "finalization_in_progress", False)):
            return
        self._state.finalization_in_progress = True
        report = RunCompletionReport()
        log = lambda message, level: _safe_log(self._log, message, level)
        try:
            report.shutdown_requested = bool(self._ui.shut_cb.isChecked())
            aborted = bool(getattr(finished_thread, "abort_requested", False))
            if report.shutdown_requested or aborted:
                self._state.watch_intake_blocked = True
            self._archive_restored_journal()
            report.move_log = list(getattr(self._state, "move_report_log", []) or []) + list(move_log or [])
            report.move_ok = int(getattr(self._state, "move_ok_count", 0) or 0) + int(move_ok or 0)
            report.move_errors = int(getattr(self._state, "move_error_count", 0) or 0) + int(move_errors or 0)
            report_completion(report, finished_thread, did_shutdown=did_shutdown,
                log_summary=self.log_run_summary, show_reminders=self._show_replacement_reminders,
                show_summary=self._show_run_summary_dialog, log=log)
            notify_completion(getattr(self, "_notifications", None), finished_thread,
                report, build_summary=self._build_run_summary, log=log)
        except Exception:
            notify_finalization_error(getattr(self, "_notifications", None), traceback.format_exc(), log=log)
        finally:
            try:
                self._finish_job_journal(finished_thread,
                    status="aborted" if getattr(finished_thread, "abort_requested", False) else "completed")
            finally:
                try:
                    self._clear()
                except Exception as exc:
                    log(f"⚠️ Run-Aufräumen fehlgeschlagen: {exc}", "warn")
                self._state.summary_written = True
        try:
            if report.retry_files:
                if self._requeue_files:
                    self._requeue_files(report.retry_files)
                    log(f"{len(report.retry_files)} Fehlerdatei(en) erneut in die Queue gelegt.", "warn")
            elif report.shutdown_requested and not did_shutdown:
                self._confirm_shutdown()
        except Exception:
            notify_finalization_error(getattr(self, "_notifications", None), traceback.format_exc(), log=log)
        finally:
            self._state.finalization_in_progress = False

    def _archive_restored_journal(self) -> None:
        restored = str(getattr(self._state, "restored_job_journal_path", "") or "")
        if not restored:
            return
        try:
            from ..core.job_journal import archive_job_journal_path
            archive_job_journal_path(restored, status="resumed_by_run")
            self._state.restored_job_journal_path = ""
        except Exception as exc:
            _safe_log(self._log, f"⚠️ Vorgänger-Job-Journal konnte nicht archiviert werden: {exc}", "warn")

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
                ids_text = (
                    ", ".join(removed_ids)
                    if removed_ids
                    else f"{removed} Eintrag/Einträge"
                )
                self._log(
                    "✅ Ersetzungs-Erinnerung bestätigt und aus der Erinnerungsliste "
                    f"gelöscht: {ids_text}",
                    "info",
                )
        except Exception as exc:
            self._log(
                f"Ersetzungs-Erinnerungen konnten nicht angezeigt werden: {exc}",
                "warn",
            )

    def log_run_summary(
        self,
        finished_thread,
        move_log: list,
        move_ok: int,
        move_errors: int,
    ) -> None:
        logger = getattr(finished_thread, "_logger", None) if finished_thread else None
        is_dv_remux = bool(
            finished_thread and finished_thread.__class__.__name__ == "DVRemuxThread"
        )
        if logger is not None and not is_dv_remux:
            total_before = getattr(finished_thread, "total_before", 0)
            total_after = getattr(finished_thread, "total_after", 0)
            run_start = getattr(finished_thread, "_run_start_ts", None)
            total_duration_s = time.time() - run_start if run_start else 0
            replace_service = getattr(finished_thread, "_replace_service", None)
            archived = getattr(replace_service, "archiviert", 0)
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
                archiviert=archived,
            )
        elif logger is not None and is_dv_remux:
            logger.info("DV-Remux abgeschlossen.")
            logger.move_summary(move_log, move_ok, move_errors)

    def _finish_job_journal(self, finished_thread, *, status: str) -> None:
        journal = getattr(self._state, "job_journal", None)
        if journal is None:
            return
        try:
            journal.finish_run(status=status)
        except Exception as exc:
            _safe_log(self._log, f"⚠️ Job-Journal konnte nicht finalisiert werden: {exc}", "warn")
        self._state.job_journal = None
        self._state.job_journal_current_path = None
        self._state.job_journal_current_paths.clear()

    def _build_run_summary(self, finished_thread, *, move_ok: int, move_errors: int) -> dict:
        replace_service = (
            getattr(finished_thread, "_replace_service", None) if finished_thread else None
        )
        return build_run_summary(
            list(self._state.run_results.values()),
            total_before=getattr(finished_thread, "total_before", 0),
            total_after=getattr(finished_thread, "total_after", 0),
            move_ok=move_ok,
            move_errors=move_errors,
            archived=getattr(replace_service, "archiviert", 0),
        )

    def _show_run_summary_dialog(
        self,
        finished_thread,
        *,
        move_ok: int,
        move_errors: int,
    ) -> list[str]:
        try:
            from .run_summary_dialog import RunSummaryDialog

            summary = self._build_run_summary(
                finished_thread,
                move_ok=move_ok,
                move_errors=move_errors,
            )
            dialog = RunSummaryDialog(summary, parent=self._parent_widget)
            try:
                dialog.exec()
                if dialog.action() == RunSummaryDialog.ACTION_REQUEUE_FAILED:
                    return dialog.failed_inputs()
            finally:
                dialog.deleteLater()
        except Exception:
            self._log("Abschlussdialog konnte nicht angezeigt werden.", "warn")
            self._log(traceback.format_exc(), "error")
        return []
