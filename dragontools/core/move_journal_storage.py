# -*- coding: utf-8 -*-
from __future__ import annotations
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from .path_defaults import app_documents_dir
from .json_io import atomic_write_json as _atomic_write_json
from .move_journal_contracts import ACTIVE_MOVE_JOURNAL_NAME, JOURNAL_FILE_PREFIX, ARCHIVE_DIR_NAME, CLOSED_MOVE_STATUSES
from .move_journal_utils import _read_json_dict, _unique_archive_path, _now
from .journal_runtime import recovery_may_run

_LOG = logging.getLogger(__name__)

def move_journal_dir(root: str | Path | None = None) -> Path:
    path = app_documents_dir(root) / "MoveJournal"
    path.mkdir(parents=True, exist_ok=True)
    return path

def active_move_journal_path(root: str | Path | None = None) -> Path:
    return move_journal_dir(root) / ACTIVE_MOVE_JOURNAL_NAME

def new_move_journal_path(root: str | Path | None = None) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return move_journal_dir(root) / f"{JOURNAL_FILE_PREFIX}{stamp}_{uuid.uuid4().hex[:8]}.json"

def list_move_journal_paths(root: str | Path | None = None) -> list[Path]:
    folder = move_journal_dir(root)
    paths: list[Path] = []
    legacy = folder / ACTIVE_MOVE_JOURNAL_NAME
    if legacy.exists():
        paths.append(legacy)
    paths.extend(
        path
        for path in folder.glob(f"{JOURNAL_FILE_PREFIX}*.json")
        if path.is_file()
    )
    paths.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return paths

def read_move_journal_path(path: str | Path) -> dict[str, Any] | None:
    journal_path = Path(path)
    if not journal_path.exists():
        return None
    data = _read_json_dict(journal_path)
    if not isinstance(data, dict) or not data.get("active"):
        return None
    if str(data.get("status") or "").lower() in CLOSED_MOVE_STATUSES:
        return None
    data["_journal_path"] = str(journal_path)
    return data

def read_active_move_journals(root: str | Path | None = None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in list_move_journal_paths(root):
        data = read_move_journal_path(path)
        if data:
            result.append(data)
    return result

def read_active_move_journal(root: str | Path | None = None) -> dict[str, Any] | None:
    journals = read_active_move_journals(root)
    return next((data for data in journals if recovery_may_run(data, data['_journal_path'])), None)

def archive_move_journal_path(journal_path: str | Path, *, status: str = "ignored") -> Path | None:
    from .journal_archive import archive_journal
    path = Path(journal_path)
    if not path.exists():
        return None
    data = _read_json_dict(path)
    if data and data.get('active') and not recovery_may_run(data, path):
        raise OSError('Ein laufendes Move-Journal darf nicht archiviert werden.')
    return archive_journal(path, status=status, write=_atomic_write_json)


def archive_active_move_journal(
    *,
    status: str = "ignored",
    root: str | Path | None = None,
    journal_path: str | Path | None = None,
) -> Path | None:
    """Archiviert ein offenes Move-Journal. Ohne journal_path wird das neueste gewählt."""
    path = Path(journal_path) if journal_path else None
    if path is None:
        data = read_active_move_journal(root)
        if data and data.get("_journal_path"):
            path = Path(str(data["_journal_path"]))
        else:
            legacy = active_move_journal_path(root)
            path = legacy if legacy.exists() else None
    if path is None:
        return None
    return archive_move_journal_path(path, status=status)
