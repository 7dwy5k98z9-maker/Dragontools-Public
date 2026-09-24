# -*- coding: utf-8 -*-
"""Qt-independent facade for transactional file and directory moves."""
from __future__ import annotations

# Keep module references public for existing diagnostics/tests that monkeypatch
# these standard modules through ``move_file_service``.
import os
import shutil
from pathlib import Path
from typing import Callable, Protocol

from .episode_replacement_policy import (
    allow_identity_replacement,
    identity_only_episode_conflicts,
    normalize_episode_replacement_mode,
)
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
from .move_preparation import MovePreparationService
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
        "episode_identity_replacement_declined": False,
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
        episode_replacement_mode: str = "auto",
        confirm_episode_replacement: Callable[[dict], bool] | None = None,
    ) -> None:
        self.conflict_mode = conflict_mode
        self._log = log
        self._wait = wait
        self._abort_immediately = abort_immediately
        self._journal = journal
        self.episode_replacement_mode = normalize_episode_replacement_mode(episode_replacement_mode)
        self._confirm_episode_replacement = confirm_episode_replacement
        self._journal_ops = MoveJournalAdapter(journal)
        self._conflicts = MoveConflictTransactions(log=log, journal=self._journal_ops)
        self._transfer = MoveTransferExecutor(
            log=log, wait=wait, abort_immediately=abort_immediately,
            journal=self._journal_ops, conflicts=self._conflicts,
        )
        self.last_result: dict | None = None

    def _preparation_service(self) -> MovePreparationService:
        return MovePreparationService(
            conflict_mode=self.conflict_mode,
            log=self._log,
            journal_set_destination=self._journal_set_destination,
            allow_episode_replacement=self._allow_episode_identity_replacement,
            describe_episode_replacement=lambda result, dst, conflicts, artifacts: (
                self._prepare_episode_identity_replacement(result, dst, conflicts, artifacts)
            ),
        )

    def prepare_move(self, src, dst_dir, *, dest_name: str | None = None) -> dict:
        prepared = self._preparation_service().prepare(src, dst_dir, dest_name=dest_name)
        self.last_result = dict(prepared.get("result") or {})
        return prepared

    def move(
        self,
        src,
        dst_dir,
        hook=None,
        *,
        dest_name: str | None = None,
        prepared: dict | None = None,
        protected_paths=None,
    ) -> tuple[bool, dict]:
        prepared = dict(prepared or self.prepare_move(src, dst_dir, dest_name=dest_name))
        result = dict(prepared.get("result") or new_move_result(src, dst_dir, dest_name=dest_name))
        prepared["result"] = result
        self.last_result = result
        src_p = Path(src)
        dp = Path(str(prepared.get("target_dir") or dst_dir))
        dp.mkdir(parents=True, exist_ok=True)
        dst_p = Path(str(prepared.get("dest_path") or (dp / (dest_name or src_p.name))))
        result["target_dir"] = str(dp)
        result["dest_path"] = str(dst_p)
        self._journal_set_destination(src_p, dst_p)

        if not bool(prepared.get("ready", True)):
            return False, result
        if src_p.is_dir():
            return self.move_directory(src_p, dst_p, result), result
        if bool(prepared.get("same_path")) or (dst_p.exists() and same_path(src_p, dst_p)):
            result["ok"] = True
            self._log(f"ℹ️ Datei liegt bereits im Zielordner: {dst_p.name}", "info")
            return True, result

        commit = self._preparation_service().resolve_commit(
            prepared, src_p=src_p, dst_p=dst_p, protected_paths=protected_paths
        )
        if not bool(commit.get("ok")):
            self.last_result = result
            return False, result

        conflicts = list(commit.get("transaction_conflicts") or [])
        backup_pairs: list[dict[str, str]] = []
        if conflicts:
            prepared_backups = self.backup_conflicts_transactional(src_p, conflicts, result)
            if prepared_backups is None:
                return False, result
            backup_pairs = prepared_backups

        ok = self._transfer.move_file(
            src_p,
            dst_p,
            result,
            backup_pairs,
            replacement_mode=commit.get("replacement_mode"),
            hook=hook,
        )
        return ok, result

    def _allow_episode_identity_replacement(
        self, result: dict, dst_p: Path, episode_conflicts: list[Path]
    ) -> bool:
        identity_only = identity_only_episode_conflicts(dst_p, episode_conflicts)
        if not identity_only:
            return True
        allowed = allow_identity_replacement(
            self.episode_replacement_mode,
            dst_p=dst_p,
            conflicts=identity_only,
            ask=self._confirm_episode_replacement,
        )
        if allowed:
            return True
        result["skipped_conflict"] = True
        result["episode_identity_replacement_declined"] = True
        names = format_conflict_names(identity_only)
        if self.episode_replacement_mode == "never":
            self._log(f"⚠️ SxxExx-Ersetzung deaktiviert, übersprungen: {names}", "warn")
        else:
            self._log(f"ℹ️ SxxExx-Ersetzung nicht bestätigt, übersprungen: {names}", "info")
        return False

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
