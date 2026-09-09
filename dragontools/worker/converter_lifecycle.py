# -*- coding: utf-8 -*-
"""Fehlergrenze und Abschlussarbeiten für ConverterThread.run()."""
from __future__ import annotations

from pathlib import Path

from ..core.crash_guard import mark_activity, write_manual_crash_note
from ..core.logger import discard_verbose_after_clean_run
from .worker_contracts import normalize_worker_path


class ConverterLifecycleService:
    """Kapselt Run-Exception-Recovery und idempotente Session-Abschlussarbeiten."""

    def __init__(self, worker) -> None:
        self._worker = worker

    def handle_run_exception(self, exc: Exception, traceback_text: str) -> None:
        worker = self._worker
        worker.log("❌ Kritischer Fehler im Konvertierungsworker.", "error")
        worker.log(str(exc) or exc.__class__.__name__, "error")
        worker.log(traceback_text, "error")
        try:
            worker._verbose_logger.write(traceback_text)
        except Exception as verbose_exc:
            worker.log(
                f"Verbose-Fehlerlog konnte nicht geschrieben werden: {verbose_exc}",
                "warn",
            )

        crash_report = ""
        try:
            crash_report = write_manual_crash_note(
                "Kritischer Fehler im Konvertierungsworker.",
                traceback_text=traceback_text,
            )
            worker.log(f"Crashbericht: {crash_report}", "error")
        except Exception as report_exc:
            worker.log(
                f"Crashbericht konnte nicht erstellt werden: {report_exc}",
                "error",
            )

        open_files = self._open_files_for_run_exception()
        if not open_files:
            return

        worker.log(
            f"❌ {len(open_files)} offene Datei(en) werden wegen des Worker-Fehlers "
            "als fehlgeschlagen markiert.",
            "error",
        )
        for path in open_files:
            worker._session_state.failure_details.setdefault(
                path,
                {
                    "message": "Kritischer Fehler im Konvertierungsworker.",
                    "error_report": crash_report,
                    "pipeline": "",
                    "container": "",
                    "strategy": "worker_run",
                },
            )
            try:
                worker._services.result.fail_unhandled(path)
            except Exception as emit_exc:
                worker.log(
                    f"❌ Fehlerstatus konnte für {Path(path).name} nicht gemeldet werden: "
                    f"{emit_exc}",
                    "error",
                )

    def _open_files_for_run_exception(self) -> list[str]:
        worker = self._worker
        with worker._files_lock:
            current = worker._queue.current_file
            queued = list(worker._queue.files)
            done_keys = {normalize_worker_path(path) for path in worker._queue.done_files}

        candidates: list[str] = []
        if current:
            candidates.append(current)
        candidates.extend(queued)
        if not candidates:
            candidates.extend(worker._session_state.all_input_files)

        result: list[str] = []
        seen: set[str] = set()
        for path in candidates:
            key = normalize_worker_path(path)
            if not key or key in seen or key in done_keys:
                continue
            seen.add(key)
            result.append(path)
        return result

    def finalize_run(self) -> None:
        self._wait_for_postprocess_jobs()
        self._cleanup_empty_temp_overwrite_dirs_after_run()
        self._discard_verbose_log_after_clean_run()
        mark_activity("Konvertierungsworker beendet")

    def _wait_for_postprocess_jobs(self) -> None:
        worker = self._worker
        coordinator = worker._services.postprocess_coordinator
        if coordinator is None:
            return
        try:
            coordinator.wait_for_all()
        except Exception as exc:
            worker.log(
                f"🧩 Post-Processing konnte nicht vollständig abgewartet werden: {exc}",
                "warn",
            )

    def _cleanup_empty_temp_overwrite_dirs_after_run(self) -> None:
        worker = self._worker
        if not worker._job_state.overwrite_original or worker._session_state.suppress_session_header:
            return
        try:
            base_dirs = {
                Path(path).parent for path in worker._session_state.all_input_files if str(path or "")
            }
            worker._services.cleanup.cleanup_empty_overwrite_dirs(base_dirs)
        except Exception as exc:
            worker.log(
                f"📝 Temporäre Overwrite-Ordner konnten nicht bereinigt werden: {exc}",
                "warn",
            )

    def _discard_verbose_log_after_clean_run(self) -> None:
        worker = self._worker
        discard_verbose_after_clean_run(
            getattr(worker, "_verbose_logger", None),
            abort_requested=bool(worker._control_state.abort_requested),
            failed_count=int(getattr(worker._runtime_state, "fehlgeschlagen", 0) or 0),
            force_keep=bool(worker._session_state.keep_verbose_log),
        )
