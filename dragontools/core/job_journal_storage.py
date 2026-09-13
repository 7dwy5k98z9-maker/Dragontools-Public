from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .json_io import atomic_write_json
from .paths import app_documents_dir

ACTIVE_JOURNAL_NAME = "active_run.json"
JOURNAL_FILE_PREFIX = "run_"
ARCHIVE_DIR_NAME = "Abgeschlossen"
CLOSED_RUN_STATUSES = {"completed", "cancelled"}
_LOG = logging.getLogger(__name__)


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
    paths.extend(path for path in folder.glob(f"{JOURNAL_FILE_PREFIX}*.json") if path.is_file())
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
    if str(data.get("status") or "").lower() in CLOSED_RUN_STATUSES:
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


def archive_job_journal_path(journal_path: str | Path, *, status: str = "ignored") -> Path | None:
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
    data["finished_at"] = now_iso()
    data["updated_at"] = data["finished_at"]

    archive_dir = path.parent / ARCHIVE_DIR_NAME
    archive_dir.mkdir(parents=True, exist_ok=True)
    run_id = str(data.get("run_id") or datetime.now().strftime("%Y%m%d_%H%M%S"))
    archive = unique_archive_path(archive_dir / f"{run_id}_{data['status']}.json")
    atomic_write_json(archive, data)
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


def unique_archive_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for idx in range(2, 10_000):
        candidate = path.with_name(f"{stem}_{idx}{suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{stem}_{datetime.now().strftime('%H%M%S')}{suffix}")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
