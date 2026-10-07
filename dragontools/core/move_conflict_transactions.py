# -*- coding: utf-8 -*-
"""Transactional backup/rollback handling for move conflicts."""
from __future__ import annotations

import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

from .move_conflicts import episode_identity_for_path
from .move_journal import MoveJournalWriteError
from .move_transaction import remove_path, publish_staged_no_replace
from .transaction_identity import path_receipt, receipt_matches


class MoveConflictTransactions:
    def __init__(self, *, log: Callable[[str, str], None], journal) -> None:
        self._log = log
        self._journal = journal
        self._owned_backups = {}

    @staticmethod
    def unique_backup_path(conflict: Path) -> Path:
        token = uuid.uuid4().hex[:10]
        return conflict.with_name(f"{conflict.name}.__dragontools_backup__{token}")

    def register_backup(self, backup):
        self._owned_backups[str(backup)] = path_receipt(backup)

    def backup(self, source_path: str | Path, conflicts: list[Path], result: dict) -> list[dict[str, str]] | None:
        pairs: list[dict[str, str]] = []
        try:
            for conflict in conflicts:
                backup = self.unique_backup_path(conflict)
                pair = {"original": str(conflict), "backup": str(backup), 'receipt': path_receipt(conflict)}
                pairs.append(pair)
                self._journal.set_backups(source_path, pairs)
                publish_staged_no_replace(conflict, backup)
                self._owned_backups[str(backup)] = path_receipt(backup)
                self._log(f"🛡️ Vorhandene Datei temporär gesichert: {conflict.name}", "info")
            result["backup_pairs"] = list(pairs)
            result["transaction_backup_count"] = len(pairs)
            return pairs
        except MoveJournalWriteError:
            self.rollback(source_path, pairs, result)
            raise
        except OSError as exc:
            self._log(f"❌ Konfliktdatei konnte nicht sicher gesichert werden: {exc}", "error")
            self.rollback(source_path, pairs, result)
            return None

    def rollback(self, source_path: str | Path, pairs: list[dict[str, str]], result: dict) -> None:
        failures: list[str] = []
        for pair in reversed(pairs):
            original = Path(pair["original"])
            backup = Path(pair["backup"])
            if not backup.exists():
                continue
            try:
                if not receipt_matches(backup, self._owned_backups.get(str(backup))):
                    failures.append(f'{backup.name}: Backup gehört nicht zu dieser Transaktion')
                    continue
                if original.exists():
                    failures.append(f"{original.name}: Original existiert bereits")
                    continue
                publish_staged_no_replace(backup, original)
                self._log(f"↩️ Vorhandene Datei wiederhergestellt: {original.name}", "warn")
            except OSError as exc:
                failures.append(f"{original.name}: {exc}")
        result["backup_pairs"] = [pair for pair in pairs if Path(pair["backup"]).exists()]
        try:
            if result["backup_pairs"]:
                self._journal.set_backups(source_path, result["backup_pairs"])
            else:
                self._journal.clear_backups(source_path)
        except MoveJournalWriteError as exc:
            self._log(f"❌ Journal konnte nach Rollback nicht synchronisiert werden: {exc}", "error")
        if failures:
            self._log("❌ Rollback der alten Zieldatei(en) unvollständig: " + "; ".join(failures), "error")

    def discard(self, source_path: str | Path, pairs: list[dict[str, str]], result: dict) -> None:
        remaining: list[dict[str, str]] = []
        for pair in pairs:
            backup = Path(pair["backup"])
            if not backup.exists():
                continue
            try:
                if not receipt_matches(backup, self._owned_backups.get(str(backup))):
                    remaining.append(pair)
                    continue
                remove_path(backup)
            except (OSError, shutil.Error) as exc:
                remaining.append(pair)
                self._log(f"⚠️ Temporäres Backup konnte nicht gelöscht werden: {backup.name} – {exc}", "warn")
        result["backup_pairs"] = remaining
        if remaining:
            self._journal.set_backups(source_path, remaining)
        else:
            self._journal.clear_backups(source_path)

    def describe_episode_replacement(
        self,
        result: dict,
        dst_p: Path,
        conflicts: list[Path],
        artifacts: list[Path] | None = None,
    ) -> None:
        identity = episode_identity_for_path(dst_p)
        if identity is None or not conflicts:
            return
        artifacts = list(artifacts or [])
        subtitle_suffixes = {".srt", ".ass", ".ssa", ".sup", ".sub", ".idx", ".vtt"}
        artifact_counts = {
            "nfo": sum(path.suffix.casefold() == ".nfo" for path in artifacts),
            "trickplay": sum(path.suffix.casefold() == ".trickplay" for path in artifacts),
        }
        subtitle_count = sum(path.suffix.casefold() in subtitle_suffixes for path in artifacts)
        if subtitle_count:
            artifact_counts["subtitle"] = subtitle_count
        result.update(
            episode_identity_replacement=True,
            episode_identity_label=identity.label,
            episode_identity_series=identity.series,
            episode_identity_season=identity.season,
            episode_identity_episode=identity.episodes[0] if identity.episodes else None,
            replacement_reason="Gleiche SxxExx-Kennung im Ziel-Staffelordner",
            replacement_reminder_required=any(
                conflict.name.casefold() != dst_p.name.casefold() for conflict in conflicts
            ),
            replacement_artifact_paths=[str(path) for path in artifacts],
            replacement_artifact_count=len(artifacts),
            replacement_artifacts_by_type=artifact_counts,
        )
        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        old_files = ", ".join(conflict.name for conflict in conflicts)
        artifact_text = ", ".join(path.name for path in artifacts) or "keine"
        self._log(
            "♻️ SxxExx-Ersetzung: "
            f"alt={old_files} | neu={dst_p.name} | Serie={identity.series or 'unbekannt'} | "
            f"{identity.label} | Zeitpunkt={timestamp} | Grund={result['replacement_reason']} | "
            f"alte Companion-Artefakte={artifact_text}",
            "warn",
        )
