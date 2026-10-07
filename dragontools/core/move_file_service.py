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
from .callback_dispatch import best_effort_callback
from .journal_runtime import journal_transaction
from .transaction_identity import validate_destination_name, receipt_matches


class JournalLike(Protocol):
    data: dict
    def set_destination(self, source_path: str, *, target_dir: str, dest_path: str) -> None: ...
    def set_backups(self, source_path: str, pairs: list[dict[str, str]]) -> None: ...
    def clear_backups(self, source_path: str) -> None: ...
    def set_cleanup_pending(self, source_path: str, *, message: str) -> None: ...


from .move_result import new_move_result


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
        self._log = lambda message, level='info', callback=log: best_effort_callback(callback, message, level)
        log = self._log
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

    @journal_transaction
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
        validate_destination_name(dest_name)
        prepared = dict(prepared or self.prepare_move(src, dst_dir, dest_name=dest_name))
        result = dict(prepared.get("result") or new_move_result(src, dst_dir, dest_name=dest_name))
        prepared["result"] = result
        self.last_result = result
        src_p = Path(src)
        self._wait()
        if self._abort_immediately():
            return False, result
        if not src_p.exists() or ('source_receipt' in prepared
                and not receipt_matches(src_p, prepared['source_receipt'])):
            result['preparation_invalidated'] = True
            result['error'] = 'Vorbereitete Quelle fehlt oder wurde verändert.'
            return False, result
        if str(prepared.get('source_path', src_p)) != str(src_p):
            raise ValueError('Move-Vorbereitung gehört zu einer anderen Quelle.')
        dp = Path(str(prepared.get("target_dir") or dst_dir))
        dp.mkdir(parents=True, exist_ok=True)
        dst_p = Path(str(prepared.get("dest_path") or (dp / (dest_name or src_p.name))))
        if dp.resolve() != Path(dst_dir).resolve() or dst_p.parent.resolve() != dp.resolve():
            raise ValueError('Move-Vorbereitung gehört zu einem anderen Ziel.')
        result["target_dir"] = str(dp)
        result["dest_path"] = str(dst_p)
        self._journal_set_destination(src_p, dst_p)

        if not bool(prepared.get("ready", True)):
            return False, result
        if src_p.is_dir():
            return self.move_directory(src_p, dst_p, result), result
        if dst_p.exists() and src_p.exists() and same_path(src_p, dst_p):
            return self._transfer.finish_existing_file(src_p, dst_p, result), result

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
