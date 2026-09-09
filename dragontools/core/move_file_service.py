# -*- coding: utf-8 -*-
"""Qt-independent facade for transactional file and directory moves."""
from __future__ import annotations

# Keep module references public for existing diagnostics/tests that monkeypatch
# these standard modules through ``move_file_service``.
import os
import shutil
from pathlib import Path
from typing import Callable, Protocol

from .move_conflict_transactions import MoveConflictTransactions
from .move_conflicts import (
    find_episode_identity_conflicts,
    find_episode_replacement_artifacts,
    find_target_conflicts,
    format_conflict_names,
    resolve_rename_path,
    same_path,
)
from .move_journal_adapter import MoveJournalAdapter
from .move_transfer_executor import MoveTransferExecutor
from .move_transaction import remove_path


class JournalLike(Protocol):
    data: dict
    def set_destination(self, source_path: str, *, target_dir: str, dest_path: str) -> None: ...
    def set_backups(self, source_path: str, pairs: list[dict[str, str]]) -> None: ...
    def clear_backups(self, source_path: str) -> None: ...
    def set_cleanup_pending(self, source_path: str, *, message: str) -> None: ...


def new_move_result(src, dst_dir, *, dest_name: str | None = None) -> dict:
    name = dest_name or Path(src).name
    return {
        "kind": "video", "name": Path(src).name, "source_path": str(src),
        "target_dir": str(dst_dir), "dest_path": str(Path(dst_dir) / name), "ok": False,
        "conflict": False, "deleted_existing": False, "deleted_existing_count": 0,
        "replaced_existing": False, "replaced_existing_count": 0,
        "backed_up_existing": False, "backed_up_existing_count": 0, "renamed": False,
        "skipped_conflict": False, "episode_identity_replacement": False,
        "episode_identity_label": "", "episode_identity_series": "",
        "episode_identity_season": None, "episode_identity_episode": None,
        "replacement_reason": "", "replacement_reminder_required": False,
        "replacement_reminder_id": "", "replacement_artifact_paths": [],
        "replacement_artifact_count": 0,
        "replacement_artifacts_by_type": {"nfo": 0, "trickplay": 0},
        "replacement_artifacts_removed_count": 0,
    }


class MoveFileService:
    """Facade that coordinates conflict policy and rollback-safe transfers."""

    def __init__(
        self,
        *,
        conflict_mode: str,
        log: Callable[[str, str], None],
        wait: Callable[[], None],
        abort_immediately: Callable[[], bool],
        journal: JournalLike | None = None,
    ) -> None:
        self.conflict_mode = conflict_mode
        self._log = log
        self._wait = wait
        self._abort_immediately = abort_immediately
        self._journal = journal
        self._journal_ops = MoveJournalAdapter(journal)
        self._conflicts = MoveConflictTransactions(log=log, journal=self._journal_ops)
        self._transfer = MoveTransferExecutor(
            log=log, wait=wait, abort_immediately=abort_immediately,
            journal=self._journal_ops, conflicts=self._conflicts,
        )
        self.last_result: dict | None = None

    def move(self, src, dst_dir, hook=None, *, dest_name: str | None = None) -> tuple[bool, dict]:
        result = new_move_result(src, dst_dir, dest_name=dest_name)
        self.last_result = result
        dp = Path(dst_dir)
        dp.mkdir(parents=True, exist_ok=True)
        src_p = Path(src)
        dst_p = dp / (dest_name or src_p.name)
        result["target_dir"] = str(dp)
        result["dest_path"] = str(dst_p)
        self._journal_set_destination(src_p, dst_p)

        if src_p.is_dir():
            return self.move_directory(src_p, dst_p, result), result
        if dst_p.exists() and same_path(src_p, dst_p):
            result["ok"] = True
            self._log(f"ℹ️ Datei liegt bereits im Zielordner: {dst_p.name}", "info")
            return True, result

        backup_pairs: list[dict[str, str]] = []
        replacement_mode: str | None = None
        conflicts = find_target_conflicts(dst_p, src_p)
        if conflicts:
            result["conflict"] = True
            result["conflict_paths"] = [str(path) for path in conflicts]
            episode_conflicts = find_episode_identity_conflicts(dst_p, src_p)
            transaction_conflicts = list(conflicts)
            if episode_conflicts:
                artifacts = find_episode_replacement_artifacts(dst_p, episode_conflicts)
                self._prepare_episode_identity_replacement(result, dst_p, episode_conflicts, artifacts)
                for artifact in artifacts:
                    if not any(same_path(artifact, current) for current in transaction_conflicts):
                        transaction_conflicts.append(artifact)
            mode = "delete_first" if episode_conflicts else self.conflict_mode
            if mode == "skip":
                result["skipped_conflict"] = True
                self._log("⚠️ Ziel existiert bereits, übersprungen: " + format_conflict_names(conflicts), "warn")
                return False, result
            if mode in {"delete_first", "overwrite"}:
                prepared = self.backup_conflicts_transactional(src_p, transaction_conflicts, result)
                if prepared is None:
                    return False, result
                backup_pairs = prepared
                replacement_mode = mode
            elif mode == "rename":
                dst_p = resolve_rename_path(dst_p, src_p)
                result["renamed"] = True
                result["dest_path"] = str(dst_p)
                self._journal_set_destination(src_p, dst_p)
                self._log(f"📝 Umbenennung: Zieldatei heißt jetzt {dst_p.name}", "info")

        ok = self._transfer.move_file(
            src_p, dst_p, result, backup_pairs,
            replacement_mode=replacement_mode, hook=hook,
        )
        return ok, result

    def _notify_progress(self, hook, amount: int) -> bool:
        return self._transfer.notify_progress(hook, amount)

    def move_directory(self, src_p: Path, dst_p: Path, result: dict) -> bool:
        return self._transfer.move_directory(src_p, dst_p, result, conflict_mode=self.conflict_mode)

    def backup_conflicts_transactional(self, source_path: str | Path, conflicts: list[Path], result: dict) -> list[dict[str, str]] | None:
        return self._conflicts.backup(source_path, conflicts, result)

    def rollback_conflict_backups(self, source_path: str | Path, pairs: list[dict[str, str]], result: dict) -> None:
        self._conflicts.rollback(source_path, pairs, result)

    def discard_conflict_backups(self, source_path: str | Path, pairs: list[dict[str, str]], result: dict) -> None:
        self._conflicts.discard(source_path, pairs, result)

    @staticmethod
    def resolve_directory_rename_path(dst_p: Path) -> Path:
        return MoveTransferExecutor.resolve_directory_rename_path(dst_p)

    def _prepare_episode_identity_replacement(self, result: dict, dst_p: Path, conflicts: list[Path], artifacts: list[Path] | None = None) -> None:
        self._conflicts.describe_episode_replacement(result, dst_p, conflicts, artifacts)

    def _unique_conflict_backup_path(self, conflict: Path) -> Path:
        return self._conflicts.unique_backup_path(conflict)

    def _finish_installed_file(self, src_p: Path, dst_p: Path, result: dict, backup_pairs: list[dict[str, str]], *, replacement_mode: str | None) -> bool:
        return self._transfer.finish_installed_file(
            src_p, dst_p, result, backup_pairs, replacement_mode=replacement_mode
        )

    def _remove_committed_source(self, src_p: Path) -> bool:
        return self._transfer.remove_committed_source(src_p)

    # Compatibility delegates: callers/tests can keep using the historical methods.
    def _journal_tracks(self, source_path: str | Path) -> bool:
        return self._journal_ops.tracks(source_path)

    def _journal_set_destination(self, source_path: str | Path, dst_p: Path) -> None:
        self._journal_ops.set_destination(source_path, dst_p)

    def _journal_set_backups(self, source_path: str | Path, pairs: list[dict[str, str]]) -> None:
        self._journal_ops.set_backups(source_path, pairs)

    def _journal_clear_backups(self, source_path: str | Path) -> None:
        self._journal_ops.clear_backups(source_path)

    def _journal_set_cleanup_pending(self, source_path: str | Path, message: str) -> None:
        self._journal_ops.set_cleanup_pending(source_path, message)
