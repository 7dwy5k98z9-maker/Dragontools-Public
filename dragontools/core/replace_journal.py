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

from .json_io import atomic_write_json
from .paths import app_documents_dir

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
    """Rekonstruiert unterbrochene Replace-Transaktionen konservativ.

    Same-path: Backup vorhanden + Ziel fehlt -> Original wird restauriert.
    Commit bereits sichtbar -> Backup wird entfernt.
    Containerwechsel: Ziel installiert + Quelle noch vorhanden -> Cleanup wird erneut versucht.
    """
    totals = {"restored": 0, "completed": 0, "cleaned_sources": 0, "pending": 0, "failed": 0}
    for path in list_replace_journals(root):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("ungueltiges Journalformat")
            mode = str(data.get("mode") or "")
            source = Path(str(data.get("source") or ""))
            dest = Path(str(data.get("destination") or ""))
            staging = Path(str(data.get("staging") or ""))
            backup_text = str(data.get("backup") or "")
            backup = Path(backup_text) if backup_text else None

            if mode == "same_path":
                if backup is not None and backup.exists() and not dest.exists():
                    os.replace(str(backup), str(dest))
                    totals["restored"] += 1
                    path.unlink(missing_ok=True)
                    continue
                if dest.exists() and backup is not None and backup.exists() and not staging.exists():
                    _remove_path(backup)
                    totals["completed"] += 1
                    path.unlink(missing_ok=True)
                    continue
                if dest.exists() and (backup is None or not backup.exists()):
                    totals["completed"] += 1
                    path.unlink(missing_ok=True)
                    continue
                # Intent wurde geschrieben, Mutation begann aber offenbar nicht.
                if dest.exists() and staging.exists():
                    totals["completed"] += 1
                    path.unlink(missing_ok=True)
                    continue
                totals["pending"] += 1
                continue

            if mode == "container_change":
                if dest.exists() and not staging.exists():
                    if source.exists() and source.resolve() != dest.resolve():
                        try:
                            _remove_path(source)
                            totals["cleaned_sources"] += 1
                        except (OSError, shutil.Error):
                            data["status"] = "cleanup_pending"
                            data["updated_at"] = _now()
                            atomic_write_json(path, data)
                            totals["pending"] += 1
                            continue
                    totals["completed"] += 1
                    path.unlink(missing_ok=True)
                    continue
                # Noch kein Commit: Original ist unangetastet; Journal kann geschlossen werden.
                if source.exists() and staging.exists() and not dest.exists():
                    totals["completed"] += 1
                    path.unlink(missing_ok=True)
                    continue
                totals["pending"] += 1
                continue

            totals["pending"] += 1
        except (OSError, ValueError, json.JSONDecodeError, shutil.Error) as exc:
            _LOG.warning("Replace-Recovery fehlgeschlagen fuer %s: %s", path, exc)
            totals["failed"] += 1
    return totals


def _remove_path(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        path.unlink(missing_ok=True)
    else:
        shutil.rmtree(path)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
