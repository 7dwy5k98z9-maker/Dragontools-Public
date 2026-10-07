"""Best-effort run reports, independent of mandatory journal/queue completion."""
from dataclasses import dataclass, field


@dataclass
class RunCompletionReport:
    move_log: list = field(default_factory=list)
    move_ok: int = 0
    move_errors: int = 0
    shutdown_requested: bool = False
    retry_files: list[str] = field(default_factory=list)


def report_completion(report, finished_thread, *, did_shutdown, log_summary,
                      show_reminders, show_summary, log):
    try:
        log_summary(finished_thread, report.move_log, report.move_ok, report.move_errors)
    except Exception as exc:
        log(f"⚠️ Run-Zusammenfassung konnte nicht geloggt werden: {exc}", "warn")
    if report.shutdown_requested:
        if not did_shutdown:
            log("ℹ️ Abschlussbericht wird wegen aktiviertem Herunterfahren nicht geöffnet.", "info")
        return
    try:
        show_reminders()
    except Exception as exc:
        log(f"⚠️ Ersetzungs-Erinnerungen konnten nicht angezeigt werden: {exc}", "warn")
    try:
        report.retry_files = list(show_summary(finished_thread,
            move_ok=report.move_ok, move_errors=report.move_errors) or [])
    except Exception as exc:
        log(f"⚠️ Abschlussdialog konnte nicht angezeigt werden: {exc}", "warn")


def notify_completion(notifications, finished_thread, report, *, build_summary, log):
    if notifications is None or report.retry_files:
        return
    try:
        notifications.on_run_finished(build_summary(finished_thread,
            move_ok=report.move_ok, move_errors=report.move_errors),
            aborted=bool(getattr(finished_thread, "abort_requested", False)))
    except Exception as exc:
        log(f"⚠️ Abschlussbenachrichtigung fehlgeschlagen: {exc}", "warn")


def notify_finalization_error(notifications, details: str, *, log):
    if notifications is not None:
        try:
            notifications.on_internal_error("Dragon Tools Abschlussfehler", details)
        except Exception as exc:
            log(f"⚠️ Interne Fehlerbenachrichtigung fehlgeschlagen: {exc}", "warn")
    log("❌ Unbehandelte Ausnahme in finalize_run()", "error")
    log(details, "error")
