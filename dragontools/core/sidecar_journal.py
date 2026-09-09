# -*- coding: utf-8 -*-
"""Durables Journal fuer Sidecar-Commit-Transaktionen.

Sidecars werden bei Overwrite-Workflows vor dem finalen Video-Replace auf den
Ziel-Stem verschoben. Das Journal beschreibt den vollstaendigen Sidecar-Plan
*vor* der ersten destruktiven Mutation. Beim naechsten Programmstart kann damit
entschieden werden, ob die Sidecars auf den Vorzustand zurueckgerollt werden
muessen oder ob der bereits sichtbare Video-Commit als abgeschlossen gilt.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .json_io import atomic_write_json
from .paths import app_documents_dir

_LOG = logging.getLogger(__name__)
FORMAT_VERSION = 1
DIR_NAME = "SidecarJournal"
PREFIX = "sidecar_"


class SidecarJournalWriteError(OSError):
    """Das Sidecar-Intent konnte nicht dauerhaft gespeichert werden."""


def sidecar_journal_dir(root: str | Path | None = None) -> Path:
    path = app_documents_dir(root) / DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_sidecar_journals(root: str | Path | None = None) -> list[Path]:
    return sorted(
        sidecar_journal_dir(root).glob(f"{PREFIX}*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


class SidecarJournal:
    def __init__(self, path: Path, data: dict[str, Any]) -> None:
        self.path = Path(path)
        self.data = data
        self._lock = threading.RLock()

    @classmethod
    def start(
        cls,
        *,
        video_staging: str | Path,
        video_destination: str | Path,
        records: Iterable[dict[str, str]],
        root: str | Path | None = None,
        video_committed: bool = False,
    ) -> "SidecarJournal":
        folder = sidecar_journal_dir(root)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = folder / f"{PREFIX}{stamp}_{uuid.uuid4().hex[:8]}.json"
        now = _now()
        rows = [dict(row) for row in records]
        data = {
            "format": "DragonToolsSidecarJournal",
            "format_version": FORMAT_VERSION,
            "active": True,
            "status": "prepared",
            "video_staging": str(video_staging),
            "video_destination": str(video_destination),
            "video_committed": bool(video_committed),
            "sidecars": rows,
            "pid": os.getpid(),
            "created_at": now,
            "updated_at": now,
            "message": "",
        }
        journal = cls(path, data)
        journal.write(fatal=True)
        return journal

    def set_status(self, status: str, *, message: str = "", fatal: bool = False) -> None:
        with self._lock:
            self.data["status"] = str(status)
            self.data["message"] = str(message or "")
            self.data["updated_at"] = _now()
            self._write(fatal=fatal)

    def finish(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            _LOG.warning(
                "Sidecar-Journal konnte nach Abschluss nicht entfernt werden: %s (%s)",
                self.path,
                exc,
            )

    def write(self, *, fatal: bool = False) -> None:
        self._write(fatal=fatal)

    def _write(self, *, fatal: bool) -> None:
        try:
            atomic_write_json(self.path, self.data)
        except (OSError, TypeError, ValueError) as exc:
            if fatal:
                raise SidecarJournalWriteError(
                    f"Sidecar-Journal konnte nicht geschrieben werden: {self.path} ({exc})"
                ) from exc
            _LOG.error(
                "Sidecar-Journal konnte nicht aktualisiert werden: %s (%s)",
                self.path,
                exc,
            )


def recover_active_sidecar_journals(root: str | Path | None = None) -> dict[str, int]:
    """Rekonstruiert unterbrochene Sidecar-Commits konservativ.

    Solange das Video-Staging noch existiert, wurde der nachgelagerte Video-
    Commit nicht sichtbar abgeschlossen: Sidecars werden deshalb auf den
    Vorzustand zurueckgerollt. Ist das Staging verschwunden und der finale
    Videopfad vorhanden, gilt der Video-Commit als sichtbar; dann muessen alle
    Sidecars bereits committed sein und das Journal kann abgeschlossen werden.
    """
    totals = {"rolled_back": 0, "completed": 0, "pending": 0, "failed": 0}
    for path in list_sidecar_journals(root):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("ungueltiges Journalformat")
            if data.get("format") != "DragonToolsSidecarJournal":
                raise ValueError("unbekanntes Sidecar-Journalformat")
            rows = data.get("sidecars")
            if not isinstance(rows, list) or not rows:
                raise ValueError("Sidecar-Journal enthaelt keinen Commit-Plan")

            staging_text = str(data.get("video_staging") or "")
            destination_text = str(data.get("video_destination") or "")
            staging = Path(staging_text) if staging_text else None
            destination = Path(destination_text) if destination_text else None

            if bool(data.get("video_committed", False)):
                _complete_records(rows)
                totals["completed"] += 1
                path.unlink(missing_ok=True)
                continue

            if staging is not None and _path_exists(staging):
                _rollback_records(rows)
                totals["rolled_back"] += 1
                path.unlink(missing_ok=True)
                continue

            if destination is not None and _path_exists(destination):
                _complete_records(rows)
                totals["completed"] += 1
                path.unlink(missing_ok=True)
                continue

            data["status"] = "recovery_pending"
            data["message"] = "Weder Video-Staging noch finales Video sind eindeutig vorhanden."
            data["updated_at"] = _now()
            atomic_write_json(path, data)
            totals["pending"] += 1
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            _LOG.warning("Sidecar-Recovery fehlgeschlagen fuer %s: %s", path, exc)
            totals["failed"] += 1
    return totals


def _rollback_records(rows: list[dict[str, Any]]) -> None:
    errors: list[str] = []
    for row in reversed(rows):
        source = Path(str(row.get("source") or ""))
        destination = Path(str(row.get("destination") or ""))
        backup_text = str(row.get("backup") or "")
        backup = Path(backup_text) if backup_text else None
        try:
            source_exists = _path_exists(source)
            dest_exists = _path_exists(destination)
            backup_exists = backup is not None and _path_exists(backup)

            if backup_exists and source_exists and dest_exists:
                raise FileExistsError(
                    "Sidecar-Zustand ist mehrdeutig: Staging, Ziel und Backup existieren gleichzeitig."
                )

            # Neuer Sidecar wurde bereits auf das Ziel committed -> zurueck ins Staging.
            if not source_exists and dest_exists:
                source.parent.mkdir(parents=True, exist_ok=True)
                os.replace(str(destination), str(source))
                dest_exists = False

            # Altbestand wurde bereits auf Backup verschoben -> Originalnamen restaurieren.
            if backup_exists:
                if dest_exists or _path_exists(destination):
                    raise FileExistsError(
                        f"Sidecar-Rollback-Ziel ist belegt: {destination}"
                    )
                os.replace(str(backup), str(destination))
        except Exception as exc:  # Recovery darf weitere Journale trotzdem bearbeiten.
            errors.append(f"{destination.name}: {exc}")

    if errors:
        raise OSError("; ".join(errors))


def _complete_records(rows: list[dict[str, Any]]) -> None:
    """Fuehrt einen bereits logisch committed Sidecar-Plan deterministisch zu Ende."""
    for row in rows:
        source = Path(str(row.get("source") or ""))
        destination = Path(str(row.get("destination") or ""))
        backup_text = str(row.get("backup") or "")
        backup = Path(backup_text) if backup_text else None

        source_exists = _path_exists(source)
        dest_exists = _path_exists(destination)
        backup_exists = backup is not None and _path_exists(backup)

        if backup is not None:
            if source_exists and dest_exists and backup_exists:
                raise FileExistsError(
                    f"Sidecar-Zustand ist mehrdeutig: {destination}"
                )
            if source_exists and dest_exists and not backup_exists:
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.replace(str(destination), str(backup))
                dest_exists = False
                backup_exists = True
            if source_exists and not dest_exists and backup_exists:
                os.replace(str(source), str(destination))
                continue
            if not source_exists and dest_exists and backup_exists:
                continue
            raise FileNotFoundError(
                f"Sidecar-Commit kann nicht eindeutig vervollstaendigt werden: {destination}"
            )

        if source_exists and not dest_exists:
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(str(source), str(destination))
            continue
        if not source_exists and dest_exists:
            continue
        raise FileExistsError(
            f"Sidecar-Commit ohne Altbestand ist mehrdeutig: {destination}"
        )


def _path_exists(path: Path) -> bool:
    return bool(str(path)) and (path.exists() or path.is_symlink())


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
