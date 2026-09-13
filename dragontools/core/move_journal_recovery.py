# -*- coding: utf-8 -*-
"""Crash-Recovery fuer unvollstaendige Move-Journal-Eintraege."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .move_journal_utils import _normalize_status, _now, _remove_path


@dataclass
class _RecoveryCounts:
    restored: int = 0
    kept: int = 0
    failed: int = 0
    completed: int = 0
    cleaned: int = 0
    ambiguous: int = 0
    changed: bool = False

    def as_result(self) -> dict[str, int]:
        return {
            "restored": self.restored,
            "kept": self.kept,
            "failed": self.failed,
            "completed": self.completed,
            "cleaned": self.cleaned,
            "ambiguous": self.ambiguous,
        }


def _recover_pending_source_cleanup(
    row: dict[str, Any],
    source: Path | None,
    *,
    source_exists: bool,
    dest_exists: bool,
    phase: str,
    counts: _RecoveryCounts,
) -> bool:
    if not (row.get("cleanup_pending") and dest_exists and source_exists and source is not None):
        return source_exists
    try:
        _remove_path(source)
    except OSError:
        counts.failed += 1
        return source_exists

    row["cleanup_pending"] = False
    row["cleanup_message"] = ""
    row["status"] = "running" if phase == "sidecars_pending" else "ok"
    if phase != "sidecars_pending":
        row["phase"] = "completed"
    row["message"] = "Cleanup nach Crash erfolgreich abgeschlossen"
    row["finished_at"] = row.get("finished_at") or _now()
    counts.cleaned += 1
    counts.changed = True
    return False


def _classify_recovered_move_state(
    row: dict[str, Any],
    *,
    status: str,
    phase: str,
    commit_proven: bool,
    ambiguous_state: bool,
    counts: _RecoveryCounts,
) -> None:
    if status in {"running", "warn"} and commit_proven and phase != "sidecars_pending":
        row["status"] = "ok"
        row["finished_at"] = row.get("finished_at") or _now()
        row["message"] = str(row.get("message") or "Nach Crash als abgeschlossen erkannt")
        row.pop("recovery_status", None)
        counts.completed += 1
        counts.changed = True
        return
    if not ambiguous_state:
        return

    recovery_message = (
        "Recovery mehrdeutig: Quelle und Ziel existieren; "
        "Altbestand-Backup bleibt erhalten und es erfolgt keine automatische Bereinigung."
    )
    if row.get("recovery_status") != "ambiguous_source_and_destination":
        row["recovery_status"] = "ambiguous_source_and_destination"
        counts.changed = True
    if row.get("message") != recovery_message:
        row["message"] = recovery_message
        counts.changed = True
    counts.ambiguous += 1


def _recover_backup_pairs(
    row: dict[str, Any],
    *,
    commit_proven: bool,
    ambiguous_state: bool,
    counts: _RecoveryCounts,
) -> None:
    pairs = row.get("backup_pairs") if isinstance(row.get("backup_pairs"), list) else []
    remaining: list[dict[str, str]] = []
    for pair in pairs:
        if not isinstance(pair, dict):
            continue
        original_text = str(pair.get("original") or "")
        backup_text = str(pair.get("backup") or "")
        if not original_text or not backup_text:
            continue
        original = Path(original_text)
        backup = Path(backup_text)
        if not backup.exists():
            counts.changed = True
            continue
        if commit_proven:
            try:
                _remove_path(backup)
            except OSError:
                counts.failed += 1
                remaining.append({"original": original_text, "backup": backup_text})
            else:
                counts.cleaned += 1
                counts.changed = True
            continue
        if ambiguous_state or original.exists():
            counts.kept += 1
            remaining.append({"original": original_text, "backup": backup_text})
            continue
        try:
            os.replace(str(backup), str(original))
        except OSError:
            counts.failed += 1
            remaining.append({"original": original_text, "backup": backup_text})
        else:
            counts.restored += 1
            counts.changed = True
    row["backup_pairs"] = remaining


def recover_interrupted_backups(data: dict[str, Any]) -> dict[str, int]:
    """Stellt sichere Backups wieder her und erkennt Crash-Erfolge."""
    counts = _RecoveryCounts()
    files = data.get("files") if isinstance(data.get("files"), dict) else {}
    for source_text, row in files.items():
        if not isinstance(row, dict):
            continue
        dest = Path(str(row.get("dest_path") or "")) if row.get("dest_path") else None
        source = Path(str(source_text)) if source_text else None
        source_exists = bool(source and source.exists())
        dest_exists = bool(dest and dest.exists())
        status = _normalize_status(row.get("status"))
        phase = str(row.get("phase") or "")

        source_exists = _recover_pending_source_cleanup(
            row,
            source,
            source_exists=source_exists,
            dest_exists=dest_exists,
            phase=phase,
            counts=counts,
        )
        commit_proven = dest_exists and not source_exists
        ambiguous_state = dest_exists and source_exists
        _classify_recovered_move_state(
            row,
            status=status,
            phase=phase,
            commit_proven=commit_proven,
            ambiguous_state=ambiguous_state,
            counts=counts,
        )
        _recover_backup_pairs(
            row,
            commit_proven=commit_proven,
            ambiguous_state=ambiguous_state,
            counts=counts,
        )

    if counts.changed or counts.restored or counts.failed:
        data["updated_at"] = _now()
    return counts.as_result()
