# -*- coding: utf-8 -*-
"""QThread-Fassade fuer DragonTools-Verschiebevorgaenge.

Die fachlichen Verantwortlichkeiten sind auf kleine Komponenten verteilt:
- ``core.move_file_service``: Datei-/Ordnertransfer, Konflikte, Rollback
- ``core.move_routing``: Zielermittlung TV/Anime/Film
- ``core.move_sidecars``: Sidecars und Trickplay
- ``worker.move_runtime_control``: Pause/Abort/Benutzerentscheidungen
- ``worker.move_result_commit``: Service-Verdrahtung, Reporting, DB-Commit
- ``worker.move_batch_lifecycle``: Journal, Batch und Shutdown

Diese Klasse besitzt nur Qt-Signale, Initialzustand und den Run-Rahmen.
"""
from __future__ import annotations

import os  # Legacy test/diagnostic hook: move_thread.os.replace
import threading
import traceback
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from ..core.logger import create_worker_logger
from ..core.move_journal import MoveJournal
from .move_batch_executor import collect_move_files
from .move_batch_lifecycle import MoveBatchLifecycleMixin
from .move_result_commit import MoveResultCommitMixin
from .move_runtime_control import MoveRuntimeControlMixin


class MoveThread(
    MoveRuntimeControlMixin,
    MoveResultCommitMixin,
    MoveBatchLifecycleMixin,
    QThread,
):
    """Qt-Worker-Fassade fuer einen transaktionalen Move-Batch."""

    progress = pyqtSignal(int)
    move_eta = pyqtSignal(float)
    finished = pyqtSignal(bool, bool)
    request_user = pyqtSignal(str, dict)
    log_line = pyqtSignal(str)
    file_counted = pyqtSignal(int, int)

    def __init__(
        self,
        dateipfade,
        tv_path,
        anime_path,
        filme_path,
        *,
        shutdown_after=False,
        shutdown_getter=None,
        planned_targets=None,
        all_video_files=None,
        conflict_mode="skip",
        log_file_path=None,
        sidecar_outputs_by_video: "dict[str, list[str]] | None" = None,
        move_journal_root=None,
        supersedes_journal_path: str | None = None,
        companion_resume_sources: "dict[str, str] | None" = None,
    ):
        super().__init__()
        self.dateipfade = list(dateipfade or [])
        self.tv_path = tv_path
        self.anime_path = anime_path
        self.filme_path = filme_path
        self._shutdown_getter = shutdown_getter
        self.shutdown_after = shutdown_after
        self.planned_targets = dict(planned_targets or {})
        self._planned_targets_lock = threading.Lock()
        self.all_video_files = list(all_video_files or dateipfade or [])
        self.conflict_mode = (
            conflict_mode
            if conflict_mode in {"skip", "delete_first", "overwrite", "rename"}
            else "skip"
        )
        self._sidecar_outputs_by_video: dict[str, list[str]] = dict(
            sidecar_outputs_by_video or {}
        )
        self._companion_resume_sources: dict[str, str] = dict(
            companion_resume_sources or {}
        )
        self._trickplay_conflict_mode = self._read_trickplay_conflict_mode()
        self.abort_requested = False
        self.abort_type: str | None = None
        self._paused = False
        self._pause_ev = threading.Event()
        self._pause_ev.set()
        self._responses: dict = {}
        self._events: dict = {}
        self._logger = create_worker_logger(gui_callback=self.log_line.emit)
        if log_file_path:
            self._logger.log_file = Path(log_file_path)
            self._standalone_log = False
        else:
            self._standalone_log = True
        self.log_file_path = str(self._logger.log_file) if self._logger.log_file else None
        self._move_journal_root = move_journal_root
        self._move_journal: MoveJournal | None = None
        self._supersedes_journal_path = str(supersedes_journal_path or "")

    def run(self):
        moved_any = False
        did_shut = False
        self.user_declined_shutdown = False
        self._moved_log = []
        self._move_report_log = []
        self.ok_count = 0
        self.error_count = 0
        self.journal_finalize_failed = False

        if self._standalone_log:
            self._logger.move_header(len(self.dateipfade))

        try:
            files, total_bytes = collect_move_files(self.dateipfade)
            if not files:
                self.progress.emit(100)
                return

            self._start_move_journal(files)
            batch = self._execute_move_batch(files, total_bytes)
            moved_any = batch.moved_any
            self.ok_count = batch.ok_count
            self.error_count = batch.error_count

            if self.abort_requested:
                self._log("Verschieben abgebrochen.", "warn")
            else:
                self.progress.emit(100)
            self.move_eta.emit(-1.0)

            if not self.abort_requested and moved_any:
                did_shut = self._handle_optional_shutdown()
        except Exception:
            moved_any = moved_any or bool(self._moved_log)
            # Bewusste QThread-Grenze: unerwartete Fehler duerfen nicht still
            # aus dem Worker verschwinden; der Traceback landet im Log.
            self.error_count += 1
            self._log("Unbehandelte Ausnahme im Worker:", "error")
            self._log(traceback.format_exc(), "error")
        finally:
            self._finalize_journal()
            self.finished.emit(moved_any, did_shut)
