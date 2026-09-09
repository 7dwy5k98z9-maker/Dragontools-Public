# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .paths import app_documents_dir
from .json_io import atomic_write_json as _atomic_write_json


JOB_JOURNAL_VERSION = 1
ACTIVE_JOURNAL_NAME = "active_run.json"
JOURNAL_FILE_PREFIX = "run_"
ARCHIVE_DIR_NAME = "Abgeschlossen"
TERMINAL_OK_STATUSES = {"ok", "skipped"}
TERMINAL_PROBLEM_STATUSES = {"error", "warn"}
RUNNING_STATUSES = {"running"}
PENDING_STATUSES = {"queued", "unknown", ""}
_CLOSED_RUN_STATUSES = {"completed", "cancelled"}
_LOG = logging.getLogger(__name__)


class JobJournalWriteError(OSError):
    """Persistieren oder Archivieren des Job-Journals ist fehlgeschlagen.

    Ein Job-Journal darf nie so wirken, als sei ein Zustand dauerhaft gespeichert,
    wenn der atomare Schreibvorgang fehlgeschlagen ist. Der Fehler wird deshalb
    bis zur Worker-/GUI-Grenze weitergereicht.
    """


def job_journal_dir(root: str | Path | None = None) -> Path:
    path = app_documents_dir(root) / "JobJournal"
    path.mkdir(parents=True, exist_ok=True)
    return path


def active_job_journal_path(root: str | Path | None = None) -> Path:
    return job_journal_dir(root) / ACTIVE_JOURNAL_NAME


def new_job_journal_path(root: str | Path | None = None) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return job_journal_dir(root) / f"{JOURNAL_FILE_PREFIX}{stamp}_{uuid.uuid4().hex[:8]}.json"


def list_job_journal_paths(root: str | Path | None = None) -> list[Path]:
    folder = job_journal_dir(root)
    paths: list[Path] = []
    legacy = folder / ACTIVE_JOURNAL_NAME
    if legacy.exists():
        paths.append(legacy)
    paths.extend(
        path
        for path in folder.glob(f"{JOURNAL_FILE_PREFIX}*.json")
        if path.is_file()
    )
    paths.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return paths


def read_job_journal_path(path: str | Path) -> dict[str, Any] | None:
    journal_path = Path(path)
    if not journal_path.exists():
        return None
    try:
        data = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _LOG.warning("Job-Journal konnte nicht gelesen werden: %s (%s)", journal_path, exc)
        return None
    if not isinstance(data, dict) or not data.get("active"):
        return None
    if str(data.get("status") or "").lower() in _CLOSED_RUN_STATUSES:
        return None
    data["_journal_path"] = str(journal_path)
    return data


def read_active_job_journals(root: str | Path | None = None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in list_job_journal_paths(root):
        data = read_job_journal_path(path)
        if data:
            result.append(data)
    return result


def read_active_job_journal(root: str | Path | None = None) -> dict[str, Any] | None:
    journals = read_active_job_journals(root)
    return journals[0] if journals else None


def build_resume_plan(
    data: dict[str, Any],
    *,
    retry_running: bool = True,
    retry_failed: bool = False,
) -> dict[str, Any]:
    """Ermittelt aus einem aktiven Journal die Dateien für eine Wiederaufnahme."""
    files = data.get("files") if isinstance(data.get("files"), dict) else {}
    resume_files: list[str] = []
    counts = {
        "ok": 0,
        "skipped": 0,
        "failed": 0,
        "running": 0,
        "queued": 0,
        "unknown": 0,
    }

    for path, row in files.items():
        item = row if isinstance(row, dict) else {}
        status = _normalize_status(str(item.get("status") or "queued"))
        if status == "ok":
            counts["ok"] += 1
            continue
        if status == "skipped":
            counts["skipped"] += 1
            continue
        if status in TERMINAL_PROBLEM_STATUSES:
            counts["failed"] += 1
            if retry_failed:
                resume_files.append(str(path))
            continue
        if status in RUNNING_STATUSES:
            counts["running"] += 1
            if retry_running:
                resume_files.append(str(path))
            continue
        if status in PENDING_STATUSES:
            counts["queued"] += 1
            resume_files.append(str(path))
            continue

        counts["unknown"] += 1
        resume_files.append(str(path))

    return {
        "run_id": str(data.get("run_id") or ""),
        "mode": str(data.get("mode") or ""),
        "codec": str(data.get("codec") or "h265").lower(),
        "encoder": str(data.get("encoder") or ""),
        "log_file": str(data.get("log_file") or ""),
        "started_at": str(data.get("started_at") or ""),
        "updated_at": str(data.get("updated_at") or ""),
        "current_file": str(data.get("current_file") or ""),
        "current_files": [
            str(path) for path in data.get("current_files") or []
            if str(path or "")
        ],
        "files": _dedupe_preserve_order(resume_files),
        "counts": counts,
        "total_files": len(files),
        "retry_running": bool(retry_running),
        "retry_failed": bool(retry_failed),
    }


def archive_job_journal_path(
    journal_path: str | Path,
    *,
    status: str = "ignored",
) -> Path | None:
    """Archiviert genau ein Journal und entfernt nur diese aktive Datei."""
    path = Path(journal_path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _LOG.warning("Job-Journal konnte vor dem Archivieren nicht gelesen werden: %s (%s)", path, exc)
        data = {}
    if not isinstance(data, dict):
        data = {}

    data["active"] = False
    data["status"] = str(status or "ignored")
    data["finished_at"] = _now()
    data["updated_at"] = data["finished_at"]

    archive_dir = path.parent / ARCHIVE_DIR_NAME
    archive_dir.mkdir(parents=True, exist_ok=True)
    run_id = str(data.get("run_id") or datetime.now().strftime("%Y%m%d_%H%M%S"))
    archive = _unique_archive_path(archive_dir / f"{run_id}_{data['status']}.json")
    _atomic_write_json(archive, data)
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        _LOG.warning("Archiviertes Job-Journal konnte nicht entfernt werden: %s (%s)", path, exc)
    return archive


def archive_active_job_journal(
    *,
    status: str = "ignored",
    root: str | Path | None = None,
    journal_path: str | Path | None = None,
) -> Path | None:
    """Archiviert ein offenes Journal. Ohne journal_path wird das neueste gewählt."""
    path = Path(journal_path) if journal_path else None
    if path is None:
        data = read_active_job_journal(root)
        if data and data.get("_journal_path"):
            path = Path(str(data["_journal_path"]))
        else:
            legacy = active_job_journal_path(root)
            path = legacy if legacy.exists() else None
    if path is None:
        return None
    return archive_job_journal_path(path, status=status)


def format_unfinished_job_summary(data: dict[str, Any]) -> str:
    files = data.get("files") if isinstance(data.get("files"), dict) else {}
    done = sum(1 for item in files.values() if str(item.get("status") or "") in {"ok", "error", "warn", "skipped"})
    ok = sum(1 for item in files.values() if str(item.get("status") or "") == "ok")
    errors = sum(1 for item in files.values() if str(item.get("status") or "") in {"error", "warn"})
    current_files = [
        str(path) for path in data.get("current_files") or []
        if str(path or "")
    ]
    current = str(data.get("current_file") or "")
    if current and current not in current_files:
        current_files.append(current)
    lines = [
        f"Run-ID: {data.get('run_id', '-')}",
        f"Gestartet: {data.get('started_at', '-')}",
        f"Modus: {data.get('mode', '-')}",
        f"Codec: {data.get('codec', '-')}",
        f"Dateien: {done}/{len(files)} bearbeitet, {ok} OK, {errors} Fehler/Warnungen",
    ]
    if current_files:
        if len(current_files) == 1:
            lines.append(f"Letzte Datei: {Path(current_files[0]).name}")
        else:
            preview = ", ".join(Path(path).name for path in current_files[:5])
            suffix = f" (+{len(current_files) - 5})" if len(current_files) > 5 else ""
            lines.append(f"Aktive Dateien: {preview}{suffix}")
    log_file = str(data.get("log_file") or "")
    if log_file:
        lines.append(f"Log-Datei: {log_file}")
    return "\n".join(lines)


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
        now = _now()
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
            row["started_at"] = row.get("started_at") or _now()
            if index is not None:
                row["index"] = int(index)
            if total is not None:
                row["total"] = int(total)
            self._add_current_file(input_path)
            self._touch()

    def finish_file(self, input_path: str, *, output_path: str = "", status: str = "", message: str = "") -> None:
        with self._lock:
            row = self._row(input_path)
            row["status"] = _normalize_status(status)
            row["output_path"] = str(output_path or "")
            row["message"] = str(message or "")
            row["finished_at"] = _now()
            self._remove_current_file(input_path)
            self._touch()

    def finish_run(self, *, status: str = "completed") -> None:
        with self._lock:
            # Den Abschlusszustand bewusst NICHT zuerst in die aktive Datei schreiben.
            # Schlägt die Archivierung fehl, bleibt dadurch die letzte durable aktive
            # Version für die Crash-Wiederaufnahme erhalten. Erst ein erfolgreich
            # geschriebenes Archiv erlaubt das Entfernen der aktiven Datei.
            finished_at = _now()
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
        self.data["updated_at"] = _now()
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
            archive = _unique_archive_path(
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


def _normalize_status(status: str) -> str:
    text = str(status or "").strip().lower()
    if "✅" in text or text in {"ok", "success", "done"}:
        return "ok"
    if "⏭" in text or text in {"skip", "skipped"}:
        return "skipped"
    if "⚠" in text or text in {"warn", "warning"}:
        return "warn"
    if "❌" in text or text in {"error", "failed", "fail"}:
        return "error"
    return text or "unknown"


def _dedupe_preserve_order(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for path in paths:
        key = os.path.normcase(str(path))
        if key in seen:
            continue
        seen.add(key)
        result.append(str(path))
    return result


def _unique_archive_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for idx in range(2, 10_000):
        candidate = path.with_name(f"{stem}_{idx}{suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{stem}_{datetime.now().strftime('%H%M%S')}{suffix}")



def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
