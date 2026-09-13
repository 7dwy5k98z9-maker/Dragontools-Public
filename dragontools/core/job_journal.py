# -*- coding: utf-8 -*-
"""Öffentliche Job-Journal-Fassade und zustandsbehafteter Writer.

Lesen/Archivieren und Resume-Auswertung sind getrennt; der Writer bleibt hier,
damit bestehende Monkeypatch-/Fehlergrenzen für atomare Writes stabil bleiben.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .json_io import atomic_write_json as _atomic_write_json
from .job_journal_storage import (
    ACTIVE_JOURNAL_NAME, ARCHIVE_DIR_NAME, JOURNAL_FILE_PREFIX,
    active_job_journal_path, archive_active_job_journal, archive_job_journal_path,
    job_journal_dir, list_job_journal_paths, new_job_journal_path,
    now_iso, read_active_job_journal, read_active_job_journals,
    read_job_journal_path, unique_archive_path,
)
from .job_journal_resume import (
    PENDING_STATUSES, RUNNING_STATUSES, TERMINAL_PROBLEM_STATUSES,
    build_resume_plan, format_unfinished_job_summary, normalize_status,
)

JOB_JOURNAL_VERSION = 1
TERMINAL_OK_STATUSES = {"ok", "skipped"}
_LOG = logging.getLogger(__name__)


class JobJournalWriteError(OSError):
    """Persistieren oder Archivieren des Job-Journals ist fehlgeschlagen."""


class JobJournal:
    def __init__(
        self,
        path: str | Path | None = None,
        *,
        on_write_error: Callable[[str], None] | None = None,
    ) -> None:
        self.path = Path(path) if path is not None else active_job_journal_path()
        self.data: dict[str, Any] = {}
        self._lock = threading.RLock()
        self._on_write_error = on_write_error

    @classmethod
    def start(
        cls,
        *,
        files: list[str],
        codec: str,
        mode: str,
        log_file: str | None = None,
        encoder: str | None = None,
        root: str | Path | None = None,
        on_write_error: Callable[[str], None] | None = None,
    ) -> "JobJournal":
        journal = cls(new_job_journal_path(root), on_write_error=on_write_error)
        now = now_iso()
        run_id = journal.path.stem.removeprefix(JOURNAL_FILE_PREFIX)
        journal.data = {
            "format": "DragonToolsJobJournal",
            "format_version": JOB_JOURNAL_VERSION,
            "active": True,
            "status": "running",
            "run_id": run_id,
            "started_at": now,
            "updated_at": now,
            "mode": str(mode or ""),
            "codec": str(codec or ""),
            "encoder": str(encoder or ""),
            "log_file": str(log_file or ""),
            "current_file": "",
            "current_files": [],
            "pid": os.getpid(),
            "files": {
                str(path): {
                    "status": "queued",
                    "output_path": "",
                    "message": "",
                    "started_at": "",
                    "finished_at": "",
                }
                for path in files
            },
        }
        journal._write()
        return journal

    def start_file(self, input_path: str, *, index: int | None = None, total: int | None = None) -> None:
        with self._lock:
            row = self._row(input_path)
            row["status"] = "running"
            row["started_at"] = row.get("started_at") or now_iso()
            if index is not None:
                row["index"] = int(index)
            if total is not None:
                row["total"] = int(total)
            self._add_current_file(input_path)
            self._touch()

    def finish_file(self, input_path: str, *, output_path: str = "", status: str = "", message: str = "") -> None:
        with self._lock:
            row = self._row(input_path)
            row["status"] = normalize_status(status)
            row["output_path"] = str(output_path or "")
            row["message"] = str(message or "")
            row["finished_at"] = now_iso()
            self._remove_current_file(input_path)
            self._touch()

    def finish_run(self, *, status: str = "completed") -> None:
        with self._lock:
            # Den Abschlusszustand bewusst NICHT zuerst in die aktive Datei schreiben.
            # Schlägt die Archivierung fehl, bleibt dadurch die letzte durable aktive
            # Version für die Crash-Wiederaufnahme erhalten. Erst ein erfolgreich
            # geschriebenes Archiv erlaubt das Entfernen der aktiven Datei.
            finished_at = now_iso()
            self.data["active"] = False
            self.data["status"] = str(status or "completed")
            self.data["finished_at"] = finished_at
            self.data["updated_at"] = finished_at
            self._archive_completed()

    def _row(self, input_path: str) -> dict[str, Any]:
        files = self.data.setdefault("files", {})
        return files.setdefault(
            str(input_path),
            {
                "status": "queued",
                "output_path": "",
                "message": "",
                "started_at": "",
                "finished_at": "",
            },
        )

    def _touch(self) -> None:
        self.data["updated_at"] = now_iso()
        self._write()

    def _add_current_file(self, input_path: str) -> None:
        current = [
            str(path) for path in self.data.get("current_files") or []
            if str(path or "")
        ]
        value = str(input_path)
        if value not in current:
            current.append(value)
        self.data["current_files"] = current
        self.data["current_file"] = value

    def _remove_current_file(self, input_path: str) -> None:
        value = str(input_path)
        current = [
            str(path) for path in self.data.get("current_files") or []
            if str(path or "") and str(path) != value
        ]
        self.data["current_files"] = current
        self.data["current_file"] = current[-1] if current else ""

    def _notify_write_error(self, message: str) -> None:
        _LOG.exception(message)
        if self._on_write_error:
            try:
                self._on_write_error(message)
            except Exception as callback_exc:
                _LOG.warning("Job-Journal-Fehlercallback fehlgeschlagen: %s", callback_exc)

    def _write(self) -> None:
        try:
            _atomic_write_json(self.path, self.data)
        except (OSError, TypeError, ValueError) as exc:
            message = f"Job-Journal konnte nicht geschrieben werden: {self.path} ({exc})"
            self._notify_write_error(message)
            raise JobJournalWriteError(message) from exc

    def _archive_completed(self) -> Path:
        try:
            archive_dir = self.path.parent / ARCHIVE_DIR_NAME
            archive_dir.mkdir(parents=True, exist_ok=True)
            run_id = str(self.data.get("run_id") or datetime.now().strftime("%Y%m%d_%H%M%S"))
            archive = unique_archive_path(
                archive_dir / f"{run_id}_{self.data.get('status', 'completed')}.json"
            )
            _atomic_write_json(archive, self.data)
        except (OSError, TypeError, ValueError) as exc:
            message = f"Job-Journal konnte nicht archiviert werden: {self.path} ({exc})"
            self._notify_write_error(message)
            raise JobJournalWriteError(message) from exc

        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            # Das Archiv ist bereits durable. Der Fehler wird trotzdem sichtbar
            # weitergereicht, damit eine liegengebliebene aktive Datei nicht still
            # zu einem späteren Schein-Recovery-Eintrag führt.
            message = (
                "Aktives Job-Journal konnte nach erfolgreicher Archivierung nicht "
                f"entfernt werden: {self.path} ({exc})"
            )
            self._notify_write_error(message)
            raise JobJournalWriteError(message) from exc
        return archive
