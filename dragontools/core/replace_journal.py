# -*- coding: utf-8 -*-
"""Durables Journal fuer destruktive Converter-Replace-Transaktionen."""
from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from copy import deepcopy

from .json_io import atomic_write_json
from .path_defaults import app_documents_dir
from .transaction_identity import path_receipt
from .replace_recovery import recover_replace_intent
from .journal_runtime import register_journal, recovery_may_run

_LOG = logging.getLogger(__name__)
FORMAT_VERSION = 1
DIR_NAME = "ReplaceJournal"
PREFIX = "replace_"


class ReplaceJournalWriteError(OSError):
    """Das Replace-Intent konnte nicht dauerhaft gespeichert werden."""


def replace_journal_dir(root: str | Path | None = None) -> Path:
    path = app_documents_dir(root) / DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_replace_journals(root: str | Path | None = None) -> list[Path]:
    return sorted(replace_journal_dir(root).glob(f"{PREFIX}*.json"), key=lambda p: p.stat().st_mtime, reverse=True)


class ReplaceJournal:
    def __init__(self, path: Path, data: dict[str, Any]) -> None:
        self.path = Path(path)
        self.data = data
        self._lock = threading.RLock()

    @classmethod
    def start(
        cls,
        *,
        source: str | Path,
        destination: str | Path,
        staging: str | Path,
        backup: str | Path | None,
        mode: str,
        root: str | Path | None = None,
        source_receipt: dict | None = None,
        staging_receipt: dict | None = None,
    ) -> "ReplaceJournal":
        folder = replace_journal_dir(root)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = folder / f"{PREFIX}{stamp}_{uuid.uuid4().hex[:8]}.json"
        now = _now()
        data = {
            "format": "DragonToolsReplaceJournal",
            "format_version": FORMAT_VERSION,
            "active": True,
            "status": "prepared",
            "mode": str(mode),
            'source_receipt': deepcopy(source_receipt) if source_receipt is not None else (path_receipt(source) if Path(source).exists() else None),
            'staging_receipt': deepcopy(staging_receipt) if staging_receipt is not None else (path_receipt(staging) if Path(staging).exists() else None),
            "source": str(source),
            "destination": str(destination),
            "staging": str(staging),
            "backup": str(backup or ""),
            "pid": os.getpid(),
            "created_at": now,
            "updated_at": now,
            "message": "",
        }
        journal = cls(path, data)
        journal._write(fatal=True)
        register_journal(path)
        return journal

    def set_status(self, status: str, *, message: str = "", fatal: bool = False) -> None:
        with self._lock:
            self.data["status"] = str(status)
            self.data["message"] = str(message or "")
            self.data["updated_at"] = _now()
            self._write(fatal=fatal)

    def finish(self) -> None:
        """Transaktion ist komplett bereinigt; das aktive Journal wird entfernt."""
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            _LOG.warning("Replace-Journal konnte nach Abschluss nicht entfernt werden: %s (%s)", self.path, exc)

    def _write(self, *, fatal: bool) -> None:
        try:
            atomic_write_json(self.path, self.data)
        except (OSError, TypeError, ValueError) as exc:
            if fatal:
                raise ReplaceJournalWriteError(
                    f"Replace-Journal konnte nicht geschrieben werden: {self.path} ({exc})"
                ) from exc
            _LOG.error("Replace-Journal konnte nicht aktualisiert werden: %s (%s)", self.path, exc)


def recover_active_replace_journals(root: str | Path | None = None) -> dict[str, int]:
    """Recover only the source and output whose full receipts were persisted."""
    totals = {'restored': 0, 'completed': 0, 'cleaned_sources': 0, 'pending': 0, 'failed': 0}
    for path in list_replace_journals(root):
        try:
            data = json.loads(path.read_text(encoding='utf-8-sig'))
            if not isinstance(data, dict):
                raise ValueError('Ungültiges Replace-Journalformat.')
            if not recovery_may_run(data, path):
                totals['pending'] += 1
                continue
            if recover_replace_intent(data, totals):
                path.unlink(missing_ok=True)
            else:
                totals['pending'] += 1
        except (OSError, ValueError, shutil.Error) as exc:
            _LOG.warning('Replace-Recovery fehlgeschlagen für %s: %s', path, exc)
            totals['failed'] += 1
    return totals


def _remove_path(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        path.unlink(missing_ok=True)
    else:
        shutil.rmtree(path)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
