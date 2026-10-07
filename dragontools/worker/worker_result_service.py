# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable

from ..core.callback_dispatch import invoke_callback
from ..core.result_status import accepts_result
from .worker_events import progress_event, result_event
from .worker_result_accounting import WorkerResultAccounting
from .worker_contracts import normalize_worker_path
from .log_dispatch import dispatch_log


_LOG = logging.getLogger(__name__)


def _safe_emit(callback, *args) -> None:
    try:
        invoke_callback(callback, *args)
    except Exception:
        _LOG.exception("Worker-Ergebnisbeobachter fehlgeschlagen")


def _format_size(value: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    amount = float(max(0, int(value or 0)))
    unit = units[0]
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            break
        amount /= 1024.0
    if unit == "B":
        return f"{int(amount)} {unit}"
    return f"{amount:.2f} {unit}"


class WorkerConversionResultService:
    """Kapselt Fortschritts-/Ergebnis-Emission und Abschluss-Statistik."""

    def __init__(
        self,
        *,
        logger,
        runtime_state,
        overwrite_original: bool,
        event_emit: Callable,
        file_progress_emit: Callable,
        file_result_emit: Callable,
        log: Callable[[str, str], None],
        failure_details: dict[str, dict] | None = None,
    ) -> None:
        self._logger = logger
        self._runtime_state = runtime_state
        self._overwrite_original = overwrite_original
        self._event_emit = event_emit
        self._file_progress_emit = file_progress_emit
        self._file_result_emit = file_result_emit
        self._log = log
        self._failure_details = failure_details
        self._accounting = WorkerResultAccounting(runtime_state)
        self._result_lock = self._accounting.lock
        self._terminal_status: dict[str, str] = {}

    def emit_file_progress(self, path, pct, eta=None) -> None:
        event = progress_event(path, pct, eta)
        _safe_emit(self._event_emit, event)
        _safe_emit(self._file_progress_emit, path, event.percent or 0, eta)

    def emit_file_result(self, input_path: str, output_path: str, status: str) -> None:
        # Serialize the decision AND signal delivery; concurrent Future callbacks
        # must not enqueue an older success after a warning/error.
        with self._result_lock:
            key = normalize_worker_path(input_path)
            if not accepts_result(self._terminal_status.get(key), status):
                return
            self._terminal_status[key] = status
            _safe_emit(self._event_emit, result_event(input_path, output_path, status))
            if self._terminal_status[key] == status:
                _safe_emit(self._file_result_emit, input_path, output_path, status)

    def finalize_success(self, ctx) -> None:
        self.record_success(ctx)
        self.emit_file_result(ctx.input_path, ctx.final_output_path or ctx.output_path, "✅")

    def finalize_success_pending_postprocess(self, ctx) -> None:
        self.record_success(ctx)
        # AsyncPostProcessCoordinator announces the pending state before it
        # attaches a completion callback. That ordering prevents a very fast
        # postprocess from emitting ✅ before 🧩. Keep the legacy emission for
        # coordinators/extensions that do not provide that guarantee.
        if not bool(getattr(ctx, "postprocess_pending_announced", False)):
            self.emit_file_result(ctx.input_path, ctx.final_output_path or ctx.output_path, "🧩")

    def record_success(self, ctx) -> None:
        if self._accounting.recorded(ctx.input_path):
            return
        final_output = ctx.final_output_path or ctx.output_path
        if not final_output:
            raise RuntimeError("Finaler Ausgabepfad fehlt.")
        out = Path(final_output)
        if not out.exists():
            raise RuntimeError(f"Finale Ausgabedatei fehlt: {out.name}")

        sz_after = out.stat().st_size
        if not self._accounting.success(ctx.input_path, ctx.size_before, sz_after):
            return
        try:
            self._logger.file_done(
                path=ctx.input_path,
                new_path=final_output,
                sz_before=ctx.size_before,
                sz_after=sz_after,
                duration_s=time.time() - ctx.start_ts,
                overwritten=self._overwrite_original,
                start_ts=ctx.start_ts,
            )
        except Exception as exc:
            # The media transaction is already verified at this point.
            # Diagnostic logging must not turn a valid output into ❌.
            try:
                dispatch_log(self._log, f"⚠️ Abschluss-Logging fehlgeschlagen: {exc}", "warn")
            except Exception as fallback_exc:
                _LOG.error(
                    "Abschluss-Logging und Fallback-Logger fehlgeschlagen: %s",
                    fallback_exc,
                    exc_info=True,
                )
        self.emit_file_progress(ctx.input_path, 100)

    def finalize_cleanup_pending(self, ctx) -> None:
        final_output = str(getattr(ctx, "final_output_path", "") or getattr(ctx, "output_path", "") or "")
        reason = str(getattr(ctx, "cleanup_pending_message", "") or "Cleanup nach erfolgreichem Replace steht noch aus.")
        if self._failure_details is not None:
            self._failure_details[ctx.input_path] = {
                "message": reason,
                "error_report": "",
                "pipeline": str(getattr(ctx, "pipeline", "") or ""),
                "container": str(getattr(ctx, "container", "") or ""),
                "strategy": str(getattr(ctx, "strategy_name", "") or ""),
            }
        dispatch_log(self._log, f"⚠️ Replace abgeschlossen, Cleanup ausstehend: {Path(ctx.input_path).name}", "warn")
        dispatch_log(self._log, reason, "warn")
        self.emit_file_result(ctx.input_path, final_output or ctx.input_path, "⚠️")
        self.emit_file_progress(ctx.input_path, 100)
        self._accounting.failure(ctx.input_path)

    def finalize_blocked(self, ctx) -> None:
        reason = (
            str(getattr(ctx, "replacement_block_reason", "") or "")
            or "Ausgabedatei verletzt die Größenregel; Original wurde nicht ersetzt."
        )
        archived_path = (
            str(getattr(ctx, "replacement_archived_path", "") or "")
            or str(getattr(ctx, "final_output_path", "") or "")
        )
        if self._failure_details is not None:
            message = reason
            if archived_path:
                message = f"{reason} Archivierte Ausgabe: {archived_path}"
            self._failure_details[ctx.input_path] = {
                "message": message,
                "error_report": "",
                "pipeline": str(getattr(ctx, "pipeline", "") or ""),
                "container": str(getattr(ctx, "container", "") or ""),
                "strategy": str(getattr(ctx, "strategy_name", "") or ""),
            }

        dispatch_log(self._log, f"Original nicht ersetzt: {Path(ctx.input_path).name}", "warn")
        dispatch_log(self._log, reason, "warn")
        if archived_path:
            dispatch_log(self._log, f"Archivierte Ausgabe: {archived_path}", "warn")
            archived = Path(archived_path)
            size_before = int(getattr(ctx, "size_before", 0) or 0)
            if archived.exists() and size_before > 0:
                dispatch_log(self._log, 
                    f"Größe: {_format_size(size_before)} → {_format_size(archived.stat().st_size)}",
                    "warn",
                )

        self.emit_file_result(ctx.input_path, archived_path or ctx.input_path, "\u26a0\ufe0f")
        self.emit_file_progress(ctx.input_path, 100)
        self._accounting.failure(ctx.input_path)

    def fail(self, ctx, reason: str) -> None:
        report_path = str(getattr(ctx, "error_report_path", "") or "")
        archive_path = str(getattr(ctx, "replacement_archived_path", "") or "")
        message = str(reason or "")
        if archive_path:
            message = f"{message} Diagnosearchiv: {archive_path}".strip()
        if self._failure_details is not None:
            self._failure_details[ctx.input_path] = {
                "message": message,
                "error_report": report_path,
                "pipeline": str(getattr(ctx, "pipeline", "") or ""),
                "container": str(getattr(ctx, "container", "") or ""),
                "strategy": str(getattr(ctx, "strategy_name", "") or ""),
            }
        dispatch_log(self._log, f"Fehler: {Path(ctx.input_path).name}", "error")
        if reason:
            dispatch_log(self._log, reason, "error")
        if archive_path:
            dispatch_log(self._log, f"📦 Diagnosearchiv: {archive_path}", "warn")
        if report_path:
            dispatch_log(self._log, f"Fehlerbericht: {report_path}", "error")
        self.emit_file_result(ctx.input_path, archive_path or ctx.input_path, "❌")
        self.emit_file_progress(ctx.input_path, 100)
        self._accounting.failure(ctx.input_path)

    def fail_unhandled(self, input_path: str) -> None:
        self._accounting.failure(input_path)
        details = {}
        if self._failure_details is not None:
            if input_path not in self._failure_details:
                self._failure_details[input_path] = {
                    "message": "Unbehandelte Ausnahme im Converter-Worker.",
                    "error_report": "",
                    "pipeline": "",
                    "container": "",
                    "strategy": "",
                }
            details = dict(self._failure_details.get(input_path, {}) or {})
        message = str(details.get("message", "") or "Unbehandelte Ausnahme im Converter-Worker.")
        report_path = str(details.get("error_report", "") or "")
        dispatch_log(self._log, f"Fehler: {Path(input_path).name}", "error")
        dispatch_log(self._log, message, "error")
        if report_path:
            dispatch_log(self._log, f"Fehlerbericht: {report_path}", "error")
        self.emit_file_result(input_path, input_path, "❌")
        self.emit_file_progress(input_path, 100)

    def skip(self, input_path: str, reason: str) -> None:
        if self._failure_details is not None:
            self._failure_details[input_path] = {
                "message": str(reason or "Datei übersprungen."),
                "error_report": "",
                "pipeline": "",
                "container": "",
                "strategy": "source_visual_check",
            }
        dispatch_log(self._log, f"⏭️ Datei übersprungen: {Path(input_path).name}", "warn")
        if reason:
            dispatch_log(self._log, reason, "warn")
        self.emit_file_result(input_path, input_path, "⏭️")
        self.emit_file_progress(input_path, 100)
