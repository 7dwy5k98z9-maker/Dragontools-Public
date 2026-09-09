# -*- coding: utf-8 -*-
"""Lifecycle und Bedienaktionen laufender Conversion-Worker."""
from __future__ import annotations

from typing import Callable

from ..core.paths import path_compare_key


class ConversionWorkerLifecycle:
    """Kapselt Worker-Steuerung, Signalverdrahtung und Job-Journal-Lifecycle."""

    def __init__(
        self,
        *,
        state,
        ui,
        log: Callable,
        set_start_enabled: Callable[[bool], None],
        refresh_queue: Callable[[], None],
        result_service,
        progress_presenter,
        default_codec: str,
        collect_encoder_options: Callable[[], dict],
    ) -> None:
        self._state = state
        self._ui = ui
        self._log = log
        self._set_start_enabled = set_start_enabled
        self._refresh_queue = refresh_queue
        self._result_service = result_service
        self._progress = progress_presenter
        self._default_codec = default_codec
        self._collect_encoder_options = collect_encoder_options

    def active_worker(self):
        if self._state.thread and self._state.thread.isRunning():
            return self._state.thread
        if self._state.move_thread and self._state.move_thread.isRunning():
            return self._state.move_thread
        return None

    def workers_for_shutdown(self) -> tuple:
        """Alle noch gehaltenen Worker für den zentralen App-Shutdown."""
        candidates = [
            self._state.thread,
            self._state.move_thread,
            *list(self._state.retired_move_threads or []),
        ]
        result = []
        seen = set()
        for worker in candidates:
            if worker is None or id(worker) in seen:
                continue
            seen.add(id(worker))
            result.append(worker)
        return tuple(result)

    def toggle_pause(self) -> None:
        thread = self._state.thread
        if not thread:
            return
        if not (hasattr(thread, "pause") and hasattr(thread, "resume") and hasattr(thread, "_paused")):
            self._log("⏸ Pause wird von diesem Worker nicht unterstützt.", "warn")
            self._ui.pause_btn.setEnabled(False)
            self._refresh_queue()
            return
        if thread._paused:
            thread.resume()
            self._ui.pause_btn.setText("⏸ Pause")
        else:
            thread.pause()
            self._ui.pause_btn.setText("▶ Fortsetzen")
        self._refresh_queue()

    def is_file_active(self, path: str) -> bool:
        worker = self._state.thread
        if worker is None or not worker.isRunning() or not path:
            return False
        if hasattr(worker, "is_current"):
            try:
                return bool(worker.is_current(path))
            except (AttributeError, RuntimeError, TypeError, ValueError):
                return False
        active = getattr(self._state, "active_file_progress", {}) or {}
        wanted = path_compare_key(path)
        return any(path_compare_key(current) == wanted for current in active)

    def terminate_current_ffmpeg(self, path: str) -> bool:
        worker = self._state.thread
        if worker is None or not worker.isRunning() or not hasattr(worker, "terminate_current_ffmpeg"):
            self._log("Kein abbrechbarer FFmpeg-Prozess für diese Datei aktiv.", "warn")
            return False
        try:
            stopped = bool(worker.terminate_current_ffmpeg(path))
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            self._log(f"FFmpeg-Prozess konnte nicht beendet werden: {exc}", "error")
            return False
        if not stopped:
            self._log("Für diese Datei läuft aktuell kein FFmpeg-Prozess.", "warn")
        return stopped

    def abort(self) -> None:
        worker = self.active_worker()
        if not worker:
            return
        mode = "sofort" if self._ui.abort_combo.currentIndex() == 0 else "nach_datei"
        if (
            mode == "nach_datei"
            and bool(getattr(worker, "abort_requested", False))
            and getattr(worker, "abort_type", None) == "nach_datei"
            and hasattr(worker, "clear_abort_request")
        ):
            if worker.clear_abort_request():
                self._set_abort_button_default()
                self._refresh_queue()
                return
        worker.request_abort(mode)
        if mode == "nach_datei":
            if hasattr(self._ui.abort_btn, "setText"):
                self._ui.abort_btn.setText("↩️ Abbruch zurücknehmen")
            if hasattr(self._ui.abort_btn, "setToolTip"):
                self._ui.abort_btn.setToolTip(
                    "Vorgemerkten Abbruch nach der aktuellen Datei zurücknehmen"
                )
        else:
            self._set_abort_button_default()
        self._log(f"⏹ Abbruch ({mode}) ...")
        self._refresh_queue()

    def connect_worker_signals(self, worker, total_progress_slot) -> None:
        worker.log_line.connect(self._log)
        worker.file_progress.connect(self._result_service.on_file_progress)
        worker.file_result.connect(self._progress.on_file_result_cleanup)
        worker.file_result.connect(self._result_service.on_file_result)
        worker.progress.connect(total_progress_slot)
        if hasattr(worker, "dv_crop_decision_requested"):
            from .dv_crop_dialog import show_dv_crop_decision
            worker.dv_crop_decision_requested.connect(
                lambda payload, active_worker=worker: show_dv_crop_decision(active_worker, payload, log=self._log)
            )
        worker.finished.connect(self._progress.clear_active_progress_display)
        worker.finished.connect(self._result_service.on_finished)

    def start_worker_ui_state(
        self,
        worker,
        start_message: str,
        *,
        mode: str = "convert",
        files: list[str] | None = None,
    ) -> None:
        self._set_start_enabled(False)
        self._ui.abort_btn.setEnabled(True)
        self._set_abort_button_default()
        self._ui.progress_bar.setValue(0)
        log_file_path = getattr(worker, "log_file_path", None)
        self._state.current_log_path = log_file_path or None
        self._ui.curlog_btn.setEnabled(bool(log_file_path))
        journal_started = self.start_job_journal(worker, mode=mode, files=files or [])
        if journal_started is False:
            self._set_start_enabled(True)
            self._ui.abort_btn.setEnabled(False)
            self._set_abort_button_default()
            self._log(
                "❌ Konvertierung nicht gestartet: Job-Journal konnte nicht dauerhaft angelegt werden.",
                "error",
            )
            return
        self._log(start_message)
        self._progress.refresh_queue_after_file_progress(0)
        worker.start()

    def start_job_journal(self, worker, *, mode: str, files: list[str]) -> bool:
        try:
            from ..core.job_journal import JobJournal, JobJournalWriteError

            self._state.job_journal = JobJournal.start(
                files=list(files or getattr(worker, "files", []) or []),
                codec=self._default_codec,
                mode=mode,
                log_file=getattr(worker, "log_file_path", "") or "",
                encoder=str(self._collect_encoder_options().get("encoder", "")),
                on_write_error=lambda msg: self._log(
                    f"❌ {msg} – Start wird aus Sicherheitsgründen abgebrochen.", "error"
                ),
            )
        except (JobJournalWriteError, OSError, RuntimeError, TypeError, ValueError) as exc:
            self._state.job_journal = None
            self._log(f"Job-Journal konnte nicht gestartet werden: {exc}", "error")
            return False
        self._state.job_journal_current_path = None
        self._state.job_journal_current_paths.clear()
        return True

    def _set_abort_button_default(self) -> None:
        if hasattr(self._ui.abort_btn, "setText"):
            self._ui.abort_btn.setText("❌ Abbrechen")
        if hasattr(self._ui.abort_btn, "setToolTip"):
            self._ui.abort_btn.setToolTip("Aktiven Vorgang abbrechen")
