# -*- coding: utf-8 -*-
"""QThread-Orchestrator fuer DragonTools-Verschiebevorgaenge.

Die fachliche Arbeit liegt bewusst ausserhalb des Threads:
- ``core.move_file_service``: Datei-/Ordnertransfer, Konflikte, Rollback
- ``core.move_routing``: Zielermittlung TV/Anime/Film
- ``core.move_sidecars``: Sidecars und Trickplay
- ``core.move_postprocess``: Mediathek und Replacement-Reminder

MoveThread selbst verwaltet nur Threadzustand, Benutzerabfragen, Journal-
Lebenszyklus, Fortschritt und die Reihenfolge der Schritte.
"""
from __future__ import annotations

import os  # Legacy test/diagnostic hook: move_thread.os.replace
import threading
import traceback
import uuid
from pathlib import Path

from PyQt6.QtCore import QSettings, QThread, pyqtSignal

from ..core.logger import create_worker_logger
from ..core.move_file_service import MoveFileService
from ..core.move_journal import MoveJournal, MoveJournalWriteError, archive_move_journal_path
from ..core.move_postprocess import record_media_library_move
from ..core.move_routing import MoveRouter
from ..core.move_sidecars import MoveSidecarService
from ..core.settings import (
    APP_NAME,
    APP_ORG,
    DEFAULT_NFO_MOVIE_TARGET_NAME,
    DEFAULT_TRICKPLAY_CONFLICT_MODE,
    DEFAULT_TRICKPLAY_ONLY_MISSING,
    SET_KEY_NFO_MOVIE_TARGET_NAME,
    SET_KEY_TRICKPLAY_CONFLICT_MODE,
    SET_KEY_TRICKPLAY_ONLY_MISSING,
)
from ..core.system_shutdown import schedule_system_shutdown
from .move_batch_executor import MoveBatchExecutor, MoveProgressTracker, collect_move_files
from .move_completion_service import MoveCompletionService


class MoveThread(QThread):
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
        self.conflict_mode = conflict_mode if conflict_mode in {"skip", "delete_first", "overwrite", "rename"} else "skip"
        self._sidecar_outputs_by_video: dict[str, list[str]] = dict(sidecar_outputs_by_video or {})
        self._companion_resume_sources: dict[str, str] = dict(companion_resume_sources or {})
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

    # ───────────────────────────── Thread/UI control ──────────────────────────
    def provide_decision(self, rid, resp):
        self._responses[rid] = resp
        ev = self._events.get(rid)
        if ev:
            ev.set()

    def add_planned_target(self, path: str, target) -> None:
        with self._planned_targets_lock:
            if path not in self.planned_targets:
                self.planned_targets[path] = target

    def request_abort(self, mode: str = "sofort") -> None:
        self.abort_requested = True
        self.abort_type = mode
        if self._paused:
            self.resume()
        self._log(f"Abort für Verschieben angefordert ({mode}).", "warn")

    def pause(self) -> None:
        self._paused = True
        self._pause_ev.clear()
        self._log("⏸️ Verschieben pausiert.", "info")

    def resume(self) -> None:
        self._paused = False
        self._pause_ev.set()
        self._log("▶️ Verschieben fortgesetzt.", "info")

    def _wait(self) -> None:
        if getattr(self, "_paused", False):
            self._pause_ev.wait()

    def _ask(self, payload, timeout: float | None = None) -> dict:
        rid = str(uuid.uuid4())
        ev = threading.Event()
        self._events[rid] = ev
        self.request_user.emit(rid, payload)
        try:
            if timeout is None:
                while not ev.wait(timeout=0.5):
                    if self.abort_requested:
                        return {"abort": True}
            else:
                answered = ev.wait(timeout=timeout)
                if not answered:
                    self._log(
                        f"Timeout bei Benutzer-Abfrage (Typ: {payload.get('type', '?')}) - Abbruch.",
                        "warn",
                    )
            return self._responses.pop(rid, {"abort": True})
        finally:
            self._events.pop(rid, None)

    def _log(self, msg, level="info"):
        lv = (level or "info").lower()
        getattr(self._logger, lv, self._logger.info)(msg)

    # ───────────────────────────── Service factories ──────────────────────────
    def _attr(self, name: str, default=None):
        try:
            return getattr(self, name, default)
        except RuntimeError:
            return default

    def _file_service(self) -> MoveFileService:
        return MoveFileService(
            conflict_mode=self._attr("conflict_mode", "skip"),
            log=self._log,
            wait=self._wait,
            abort_immediately=lambda: bool(
                self._attr("abort_requested", False) and self._attr("abort_type", None) == "sofort"
            ),
            journal=self._attr("_move_journal", None),
        )

    def _planned_target_for(self, path: str):
        lock = self._attr("_planned_targets_lock", None)
        if lock is None:
            return self._attr("planned_targets", {}).get(path)
        with lock:
            return self.planned_targets.get(path)

    def _router(self) -> MoveRouter:
        return MoveRouter(
            tv_path=self._attr("tv_path", ""),
            anime_path=self._attr("anime_path", ""),
            filme_path=self._attr("filme_path", ""),
            all_video_files=list(self._attr("all_video_files", []) or []),
            planned_target_for=self._planned_target_for,
            ask=lambda payload: self._ask(payload),
            log=self._log,
        )

    def _sidecar_service(self) -> MoveSidecarService:
        file_service = self._file_service()
        trickplay_mode = self._attr("_trickplay_conflict_mode", None)
        if trickplay_mode is None:
            trickplay_mode = self._read_trickplay_conflict_mode()
        return MoveSidecarService(
            filme_path=self._attr("filme_path", ""),
            trickplay_conflict_mode=trickplay_mode,
            nfo_movie_target_name=self._read_nfo_movie_target_name(),
            move_file=file_service.move,
            log=self._log,
            append_report=lambda result, kind, sidecar_type: self._append_move_report(
                result, kind=kind, sidecar_type=sidecar_type
            ),
            set_last_result=lambda result: setattr(self, "_last_move_result", result),
        )

    def _completion_service(self) -> MoveCompletionService:
        return MoveCompletionService(
            journal=self._move_journal,
            move_sidecars=self._move_sidecars,
            record_media_library_move=self._record_media_library_move,
            append_move_report=self._append_move_report,
            log=self._log,
        )

    # ───────────────────────────── Move adapters ─────────────────────────────
    def _move(self, src, dst_dir, hook=None, *, dest_name: str | None = None):
        service = self._file_service()
        try:
            ok, result = service.move(src, dst_dir, hook=hook, dest_name=dest_name)
            self._last_move_result = result
            return ok
        except MoveJournalWriteError:
            if service.last_result is not None:
                self._last_move_result = service.last_result
            raise
        except Exception:
            if service.last_result is not None:
                self._last_move_result = service.last_result
            # QThread-nahe Sicherheitsgrenze fuer echte Programmier-/Callbackfehler.
            self._log(f"❌ Unbehandelte Ausnahme beim Move von {Path(src).name}", "error")
            self._log(traceback.format_exc(), "error")
            return False

    def _move_sidecars(self, video_path: str, target_dir: str) -> dict:
        sidecars = self._attr("_sidecar_outputs_by_video", {}).get(video_path, [])
        return self._sidecar_service().move_sidecars(video_path, target_dir, sidecars)

    def _record_media_library_move(self, source_path: str, move_result: dict | None) -> None:
        record_media_library_move(
            QSettings(APP_ORG, APP_NAME),
            source_path=source_path,
            move_result=move_result,
            log=self._log,
        )

    def _append_move_report(self, result: dict | None, *, kind: str = "video", sidecar_type: str | None = None) -> None:
        if not result:
            return
        entry = dict(result)
        entry["kind"] = kind
        if sidecar_type:
            entry["sidecar_type"] = sidecar_type
        if not hasattr(self, "_move_report_log"):
            self._move_report_log = []
        self._move_report_log.append(entry)

    # ───────────────────────────── Settings adapters ──────────────────────────
    def _read_trickplay_conflict_mode(self) -> str:
        settings = QSettings(APP_ORG, APP_NAME)
        mode = settings.value(SET_KEY_TRICKPLAY_CONFLICT_MODE, "", type=str)
        if mode in {"skip", "overwrite", "backup"}:
            return mode
        only_missing = settings.value(
            SET_KEY_TRICKPLAY_ONLY_MISSING,
            DEFAULT_TRICKPLAY_ONLY_MISSING,
            type=bool,
        )
        mode = "skip" if only_missing else "overwrite"
        return mode if mode in {"skip", "overwrite", "backup"} else DEFAULT_TRICKPLAY_CONFLICT_MODE

    @staticmethod
    def _read_nfo_movie_target_name() -> str:
        settings = QSettings(APP_ORG, APP_NAME)
        configured = settings.value(
            SET_KEY_NFO_MOVIE_TARGET_NAME,
            DEFAULT_NFO_MOVIE_TARGET_NAME,
            type=str,
        )
        return str(configured or DEFAULT_NFO_MOVIE_TARGET_NAME).strip()

    # ───────────────────────────── Run orchestration ──────────────────────────
    def _start_move_journal(self, files: list[tuple[str, int]]) -> None:
        self._move_journal = MoveJournal.start(
            files=[path for path, _size in files],
            target_paths={
                "tv": str(self.tv_path or ""),
                "anime": str(self.anime_path or ""),
                "film": str(self.filme_path or ""),
            },
            planned_targets=dict(self.planned_targets),
            sidecar_outputs_by_video=dict(self._sidecar_outputs_by_video),
            conflict_mode=self.conflict_mode,
            log_file=self.log_file_path,
            root=self._move_journal_root,
            on_write_error=lambda msg: self._log(
                f"❌ {msg} – Verschieben wird aus Sicherheitsgründen abgebrochen.", "error"
            ),
        )
        self._archive_superseded_journal()

    def _execute_move_batch(self, files: list[tuple[str, int]], total_bytes: int):
        progress = MoveProgressTracker(
            total_bytes,
            emit_progress=self.progress.emit,
            emit_eta=self.move_eta.emit,
        )
        executor = MoveBatchExecutor(
            files=files,
            router=self._router(),
            journal=self._move_journal,
            completion=self._completion_service(),
            companion_resume_sources=dict(self._companion_resume_sources),
            wait=self._wait,
            abort_type=lambda: self.abort_type if self.abort_requested else None,
            move=self._move,
            get_last_move_result=lambda: dict(getattr(self, "_last_move_result", None) or {}),
            set_last_move_result=lambda result: setattr(self, "_last_move_result", result),
            append_move_report=self._append_move_report,
            log=self._log,
            progress_hook=progress.update,
            file_counted=self.file_counted.emit,
        )
        try:
            return executor.run()
        finally:
            # Teilresultate bleiben auch bei einer unerwarteten Ausnahme sichtbar.
            self.ok_count = executor.result.ok_count
            self.error_count = executor.result.error_count
            self._moved_log = list(executor.result.moved_log)

    def run(self):
        moved_any = False
        did_shut = False
        self.user_declined_shutdown = False
        self._moved_log = []
        self._move_report_log = []
        self.ok_count = 0
        self.error_count = 0

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
            self._moved_log = batch.moved_log

            if self.abort_requested:
                self._log("Verschieben abgebrochen.", "warn")
            else:
                self.progress.emit(100)
            self.move_eta.emit(-1.0)

            if not self.abort_requested and moved_any:
                did_shut = self._handle_optional_shutdown()

        except Exception:
            moved_any = moved_any or bool(self._moved_log)
            # Bewusste QThread-Grenze: unerwartete Fehler duerfen nicht still aus
            # dem Worker verschwinden; der komplette Traceback landet im Log.
            self.error_count += 1
            self._log("Unbehandelte Ausnahme im Worker:", "error")
            self._log(traceback.format_exc(), "error")
        finally:
            self._finalize_journal()
            self.finished.emit(moved_any, did_shut)

    def _archive_superseded_journal(self) -> None:
        if not self._supersedes_journal_path:
            return
        try:
            archive_move_journal_path(self._supersedes_journal_path, status="restored_to_retry")
            self._supersedes_journal_path = ""
        except OSError as exc:
            self._log(f"⚠️ Altes Move-Journal konnte nach Start des Retry-Laufs nicht archiviert werden: {exc}", "warn")

    def _handle_optional_shutdown(self) -> bool:
        wants_shutdown = self._shutdown_getter() if self._shutdown_getter is not None else self.shutdown_after
        if not wants_shutdown:
            return False
        resp = self._ask({"type": "confirm_shutdown_with_countdown", "seconds": 30})
        if resp.get("ok"):
            return schedule_system_shutdown(delay_seconds=5, log=self._log)
        self.user_declined_shutdown = True
        return False

    def _finalize_journal(self) -> None:
        if self._move_journal is None:
            return
        try:
            keep_active = self._move_journal.has_retryable_files()
            if self.abort_requested:
                status = "aborted"
            elif keep_active:
                status = "incomplete"
            else:
                status = "completed"
            self._move_journal.finish_run(status=status, keep_active=keep_active)
        except (OSError, ValueError, TypeError, MoveJournalWriteError) as exc:
            self._log(f"⚠️ Move-Journal konnte nicht finalisiert werden: {exc}", "warn")
