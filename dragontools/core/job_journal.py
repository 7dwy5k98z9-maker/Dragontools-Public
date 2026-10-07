# -*- coding: utf-8 -*-
"""Öffentliche Job-Journal-Fassade und zustandsbehafteter Writer.

Lesen/Archivieren und Resume-Auswertung sind getrennt; der Writer bleibt hier,
damit bestehende Monkeypatch-/Fehlergrenzen für atomare Writes stabil bleiben.
"""
from __future__ import annotations
from copy import deepcopy

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
from .path_syntax import path_compare_key
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
        file_overrides: dict[str, dict] | None = None,
        root: str | Path | None = None,
        on_write_error: Callable[[str], None] | None = None,
    ) -> "JobJournal":
        journal = cls(new_job_journal_path(root), on_write_error=on_write_error)
        now = now_iso()
        run_id = journal.path.stem.removeprefix(JOURNAL_FILE_PREFIX)
        unique_files: list[str] = []
        seen_keys: set[str] = set()
        for raw_path in files or []:
            value = str(raw_path or "")
            key = path_compare_key(value)
            if not value or not key or key in seen_keys:
                continue
            seen_keys.add(key)
            unique_files.append(value)
        override_source = file_overrides if isinstance(file_overrides, dict) else {}
        stored_overrides: dict[str, dict] = {}
        for path in unique_files:
            wanted = path_compare_key(path)
            for raw_path, raw_override in override_source.items():
                if path_compare_key(raw_path) != wanted or not isinstance(raw_override, dict):
                    continue
                if raw_override:
                    stored_overrides[path] = dict(raw_override)
                break
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
            "queue_order": list(unique_files),
            "pid": os.getpid(),
            "file_overrides": stored_overrides,
            "files": {
                str(path): {
                    "status": "queued",
                    "output_path": "",
                    "message": "",
                    "started_at": "",
                    "finished_at": "",
                }
                for path in unique_files
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

    def update_queue_order(
        self, paths: list[str], *, file_overrides: dict[str, dict] | None = None
    ) -> None:
        """Persistiert die aktuelle sichtbare Queue-Reihenfolge atomar.

        Neu live hinzugefügte Dateien werden dabei zugleich als ``queued`` in
        das Journal aufgenommen. Entfernte wartende Dateien bleiben historisch
        in ``files`` erhalten, gehören aber nicht mehr zur Resume-Reihenfolge.
        """
        with self._lock:
            ordered: list[str] = []
            seen: set[str] = set()
            for path in paths or []:
                value = str(path or "")
                key = path_compare_key(value)
                if not value or key in seen:
                    continue
                seen.add(key)
                ordered.append(value)
                self._row(value)
            self.data["queue_order"] = ordered
            if isinstance(file_overrides, dict):
                for path in ordered:
                    override = self._override_for_path(file_overrides, path)
                    self._set_override_no_touch(path, override)
            self._touch()

    def update_file_override(self, input_path: str, override: dict | None) -> None:
        with self._lock:
            self._set_override_no_touch(input_path, override)
            self._touch()

    @staticmethod
    def _override_for_path(mapping: dict[str, dict], input_path: str) -> dict | None:
        wanted = path_compare_key(input_path)
        for raw_path, raw_override in mapping.items():
            if path_compare_key(raw_path) == wanted and isinstance(raw_override, dict):
                return deepcopy(raw_override)
        return None

    def _set_override_no_touch(self, input_path: str, override: dict | None) -> None:
        overrides = self.data.setdefault("file_overrides", {})
        wanted = path_compare_key(input_path)
        stored_key = next(
            (raw for raw in list(overrides) if path_compare_key(raw) == wanted),
            str(input_path),
        )
        if isinstance(override, dict) and override:
            overrides[stored_key] = deepcopy(override)
        else:
            for raw in list(overrides):
                if path_compare_key(raw) == wanted:
                    overrides.pop(raw, None)

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
        value = str(input_path)
        wanted = path_compare_key(value)
        for stored_path, row in files.items():
            if path_compare_key(stored_path) == wanted:
                return row
        row = {
            "status": "queued",
            "output_path": "",
            "message": "",
            "started_at": "",
            "finished_at": "",
        }
        files[value] = row
        return row

    def _touch(self) -> None:
        self.data["updated_at"] = now_iso()
        self._write()

    def _add_current_file(self, input_path: str) -> None:
        current = [
            str(path) for path in self.data.get("current_files") or []
            if str(path or "")
        ]
        value = str(input_path)
        wanted = path_compare_key(value)
        if not any(path_compare_key(path) == wanted for path in current):
            current.append(value)
        self.data["current_files"] = current
        self.data["current_file"] = value

    def _remove_current_file(self, input_path: str) -> None:
        value = str(input_path)
        wanted = path_compare_key(value)
        current = [
            str(path) for path in self.data.get("current_files") or []
            if str(path or "") and path_compare_key(str(path)) != wanted
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
            from .journal_archive import archive_journal
            archive = archive_journal(self.path, status=self.data.get('status', 'completed'),
                data=self.data, write=_atomic_write_json)
        except (OSError, TypeError, ValueError) as exc:
            message = f"Job-Journal konnte nicht archiviert werden: {self.path} ({exc})"
            self._notify_write_error(message)
            raise JobJournalWriteError(message) from exc

        return archive
