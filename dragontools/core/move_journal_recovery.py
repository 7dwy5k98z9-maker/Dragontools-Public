# -*- coding: utf-8 -*-
"""Crash-Recovery fuer unvollstaendige Move-Journal-Eintraege."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .move_journal_utils import _normalize_status, _now, _remove_path
from .move_transaction import publish_staged_no_replace
from .transaction_identity import receipt_matches, renamed_receipt_matches


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




def _collapse_same_inode_alias(
    row: dict[str, Any],
    source: Path | None,
    dest: Path | None,
    *,
    source_exists: bool,
    dest_exists: bool,
    counts: _RecoveryCounts,
) -> bool:
    """Resolve the hardlink crash window without leaving a duplicate source name.

    The file fast-path first creates a destination hardlink and only then removes
    the source name.  A hard crash in between leaves both paths pointing at the
    same regular-file inode. Only the durable receipts written before that
    mutation authorize source cleanup; missing or changed proofs retain both.
    """
    if not (source_exists and dest_exists and source is not None and dest is not None):
        return source_exists
    try:
        if source.is_symlink() or dest.is_symlink() or not source.is_file() or not dest.is_file():
            return source_exists
        src_key = os.path.normcase(os.path.abspath(str(source)))
        dst_key = os.path.normcase(os.path.abspath(str(dest)))
        if src_key == dst_key or not source.samefile(dest):
            return source_exists
        proof = row.get('commit_proof')
        if not (isinstance(proof, dict)
                and renamed_receipt_matches(source, proof.get('source'))
                and renamed_receipt_matches(dest, proof.get('destination'))):
            return source_exists
        _remove_path(source)
    except OSError:
        return source_exists

    row["cleanup_pending"] = False
    row["cleanup_message"] = ""
    row["message"] = "Hardlink-Commit nach Crash erkannt; Quellname sicher entfernt"
    counts.cleaned += 1
    counts.changed = True
    return False


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
    proof = row.get('commit_proof', {})
    destination = Path(str(row.get('dest_path') or ''))
    if not (receipt_matches(source, proof.get('source'))
            and renamed_receipt_matches(destination, proof.get('destination'))):
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
        if (original.parent.resolve() != backup.parent.resolve()
                or not backup.name.startswith(original.name + '.__dragontools_backup__')
                or backup.is_symlink()):
            counts.kept += 1
            remaining.append(pair)
            continue
        if not backup.exists():
            counts.changed = True
            continue
        if commit_proven:
            if not renamed_receipt_matches(backup, pair.get('receipt')):
                counts.kept += 1
                remaining.append(pair)
                continue
            try:
                _remove_path(backup)
            except OSError:
                counts.failed += 1
                remaining.append(pair)
            else:
                counts.cleaned += 1
                counts.changed = True
            continue
        if ambiguous_state or original.exists():
            counts.kept += 1
            remaining.append(pair)
            continue
        try:
            if pair.get('receipt') and not renamed_receipt_matches(backup, pair['receipt']):
                raise OSError('Backup wurde nach der Sicherung verändert.')
            publish_staged_no_replace(backup, original)
        except OSError:
            counts.failed += 1
            remaining.append(pair)
        else:
            counts.restored += 1
            counts.changed = True
    row["backup_pairs"] = remaining


def _completed_without_pending_work(row: dict[str, Any], status: str, phase: str) -> bool:
    """Durable completed rows need no media proofs unless cleanup remains."""
    return (status == "ok" and phase != "sidecars_pending"
            and not row.get("cleanup_pending") and not row.get("backup_pairs"))


def recover_interrupted_backups(data: dict[str, Any]) -> dict[str, int]:
    """Stellt sichere Backups wieder her und erkennt Crash-Erfolge.

    A physically committed video is not equivalent to a completed move when
    the journal still knows companion files. In that crash window recovery
    advances the phase to ``sidecars_pending`` instead of dropping the entry.
    """
    counts = _RecoveryCounts()
    files = data.get("files") if isinstance(data.get("files"), dict) else {}
    sidecars_by_video = (
        data.get("sidecar_outputs_by_video")
        if isinstance(data.get("sidecar_outputs_by_video"), dict)
        else {}
    )
    for source_text, row in files.items():
        if not isinstance(row, dict):
            continue
        status = _normalize_status(row.get("status"))
        phase = str(row.get("phase") or "")
        # A durable completed entry needs no recovery. Re-reading its full
        # video digest on every startup can scan hours of media over SMB.
        # Outstanding cleanup/backups and companion commits still need proof.
        if _completed_without_pending_work(row, status, phase):
            continue
        dest = Path(str(row.get("dest_path") or "")) if row.get("dest_path") else None
        source = Path(str(source_text)) if source_text else None
        source_exists = bool(source and source.exists())
        dest_exists = bool(dest and dest.exists())

        source_exists = _collapse_same_inode_alias(
            row,
            source,
            dest,
            source_exists=source_exists,
            dest_exists=dest_exists,
            counts=counts,
        )
        source_exists = _recover_pending_source_cleanup(
            row,
            source,
            source_exists=source_exists,
            dest_exists=dest_exists,
            phase=phase,
            counts=counts,
        )
        proof = row.get('commit_proof') if isinstance(row.get('commit_proof'), dict) else {}
        commit_proven = (dest_exists and not source_exists and dest is not None
            and renamed_receipt_matches(dest, proof.get('destination')))
        ambiguous_state = dest_exists and not commit_proven

        pending_sidecars = list(sidecars_by_video.get(str(source_text), []) or [])
        if (
            status in {"running", "warn"}
            and commit_proven
            and phase == "video_pending"
            and pending_sidecars
        ):
            row["status"] = "running"
            row["phase"] = "sidecars_pending"
            row["message"] = (
                "Video-Commit nach Crash erkannt; Companion-Dateien werden fortgesetzt"
            )
            row.pop("recovery_status", None)
            phase = "sidecars_pending"
            counts.changed = True

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
