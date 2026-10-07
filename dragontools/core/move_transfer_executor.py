# -*- coding: utf-8 -*-
"""Low-level rollback-safe file and directory transfer executor."""
from __future__ import annotations

import os
import errno
import shutil
from pathlib import Path
from typing import Callable

from .move_journal import MoveJournalWriteError
from .move_transaction import (
    PathSwapTransaction, PathTransactionRollbackError, publish_staged_no_replace,
    remove_path, unique_staging_path,
)
from .move_copy_verification import verify_staged_file_copy
from .move_conflicts import same_path
from .transaction_identity import path_receipt, receipt_matches, renamed_receipt_matches, object_identity, same_object


class MoveTransferExecutor:
    def __init__(
        self,
        *,
        log: Callable[[str, str], None],
        wait: Callable[[], None],
        abort_immediately: Callable[[], bool],
        journal,
        conflicts,
    ) -> None:
        self.log = log
        self.wait = wait
        self.abort_immediately = abort_immediately
        self.journal = journal
        self.conflicts = conflicts

    def notify_progress(self, hook, amount: int) -> bool:
        if hook is None:
            return True
        try:
            hook(amount)
            return True
        except Exception as exc:
            self.log(
                f"⚠️ Fortschritts-Callback fehlgeschlagen; Dateitransaktion wird fortgesetzt: {exc}",
                "warn",
            )
            return False

    def move_file(
        self,
        src_p: Path,
        dst_p: Path,
        result: dict,
        backup_pairs: list[dict[str, str]],
        *,
        replacement_mode: str | None,
        hook=None,
    ) -> bool:
        destination_installed = False
        tmp_p = unique_staging_path(dst_p)
        stage_identity = None
        installed_receipt = None
        source_receipt = path_receipt(src_p)
        try:
            self.check_abort()
            # Persist the expected shared inode before the hardlink crash window.
            # The actual installed receipt replaces this intent before cleanup.
            self.journal.set_commit_proof(src_p, source_receipt, source_receipt)
            try:
                os.link(str(src_p), str(dst_p))
            except OSError:
                linked = False
            else:
                linked = True
                destination_installed = True
                installed_receipt = path_receipt(dst_p)
            if linked:
                if not renamed_receipt_matches(src_p, source_receipt):
                    raise OSError('Quelle wurde während des Hardlink-Commits verändert.')
                source_receipt = path_receipt(src_p)
                self.notify_progress(hook, src_p.stat().st_size)
            else:
                progress_hook = hook
                with open(src_p, 'rb') as fsrc, open(tmp_p, 'xb') as fdst:
                    stage_identity = object_identity(tmp_p)
                    while True:
                        self.check_abort()
                        buf = fsrc.read(8 * 1024 * 1024)
                        if not buf:
                            break
                        fdst.write(buf)
                        if progress_hook is not None and not self.notify_progress(progress_hook, len(buf)):
                            progress_hook = None
                    fdst.flush()
                    os.fsync(fdst.fileno())
                verify_staged_file_copy(src_p, tmp_p)
                self.check_abort()
                if not receipt_matches(src_p, source_receipt):
                    raise OSError('Quelle wurde nach der Kopierprüfung verändert.')
                shutil.copystat(src_p, tmp_p)
                publish_staged_no_replace(tmp_p, dst_p)
                destination_installed = True
                installed_receipt = path_receipt(dst_p)
            self.check_abort()
            if not receipt_matches(src_p, source_receipt):
                raise OSError('Quelle wurde vor dem Cleanup verändert.')
            self.journal.set_commit_proof(src_p, source_receipt, installed_receipt)
            return self.finish_installed_file(src_p, dst_p, result, backup_pairs,
                replacement_mode=replacement_mode, source_receipt=source_receipt,
                destination_receipt=installed_receipt)
        except MoveJournalWriteError:
            # A persistence failure is fatal; never retry another transfer path.
            raise
        except (OSError, shutil.Error, InterruptedError) as exc:
            self.log(f'Fehler beim Verschieben: {exc}', 'error')
            if destination_installed and receipt_matches(dst_p, installed_receipt):
                remove_path(dst_p)
                destination_installed = False
            result['ok'] = False
            return False
        finally:
            if same_object(tmp_p, stage_identity):
                remove_path(tmp_p)
            if backup_pairs and not destination_installed:
                self.conflicts.rollback(src_p, backup_pairs, result)

    def check_abort(self):
        self.wait()
        if self.abort_immediately():
            raise InterruptedError('Verschieben sofort abgebrochen.')

    def finish_existing_file(self, source, destination, result):
        source_receipt = path_receipt(source)
        destination_receipt = path_receipt(destination)
        self.journal.set_commit_proof(source, source_receipt, destination_receipt)
        completed = self.finish_installed_file(source, destination, result, [],
            replacement_mode=None, source_receipt=source_receipt,
            destination_receipt=destination_receipt)
        self.log(f'Datei liegt bereits im Zielordner: {destination.name}', 'info')
        return completed

    def move_directory(self, src_p: Path, dst_p: Path, result: dict, *, conflict_mode: str) -> bool:
        from .move_directory_transfer import move_directory
        return move_directory(self, src_p, dst_p, result, conflict_mode)

    @staticmethod
    def resolve_directory_rename_path(dst_p: Path) -> Path:
        for idx in range(1, 1000):
            candidate = dst_p.parent / f"{dst_p.name}_{idx:02d}"
            if not candidate.exists():
                return candidate
        raise RuntimeError(f"Kein freier Ordnername gefunden für {dst_p.name}")

    def finish_installed_file(
        self,
        src_p: Path,
        dst_p: Path,
        result: dict,
        backup_pairs: list[dict[str, str]],
        *,
        replacement_mode: str | None,
        source_receipt=None,
        destination_receipt=None,
    ) -> bool:
        self.check_abort()
        if source_receipt is not None and not receipt_matches(src_p, source_receipt):
            raise OSError('Quelle wurde vor dem Löschen verändert.')
        if destination_receipt is not None and not receipt_matches(dst_p, destination_receipt):
            raise OSError('Installiertes Ziel wurde vor dem Cleanup verändert.')
        result["ok"] = True
        result["dest_path"] = str(dst_p)
        video_conflict_count = len(result.get("conflict_paths") or [])
        artifact_count = len(result.get("replacement_artifact_paths") or [])
        if replacement_mode == "delete_first":
            result["deleted_existing"] = bool(video_conflict_count)
            result["deleted_existing_count"] = video_conflict_count
        elif replacement_mode == "overwrite":
            result["replaced_existing"] = bool(video_conflict_count)
            result["replaced_existing_count"] = video_conflict_count
        if replacement_mode in {"delete_first", "overwrite"}:
            result["replacement_artifacts_removed_count"] = artifact_count
        try:
            src_key = os.path.normcase(os.path.abspath(str(src_p)))
            dst_key = os.path.normcase(os.path.abspath(str(dst_p)))
            if src_p.exists() and src_key != dst_key:
                src_p.unlink()
        except OSError as exc:
            message = f"Zieldatei installiert; Quelldatei konnte nicht gelöscht werden: {exc}"
            result["cleanup_pending"] = True
            result["cleanup_message"] = message
            self.journal.set_cleanup_pending(src_p, message)
            self.log(f"⚠️ {message}", "warn")
        if not result.get('cleanup_pending'):
            self.conflicts.discard(src_p, backup_pairs, result)
        return True

    def remove_committed_source(self, src_p: Path) -> bool:
        try:
            if src_p.exists() or src_p.is_symlink():
                remove_path(src_p)
            return True
        except (OSError, shutil.Error) as exc:
            self.log(f"⚠️ Ziel ist vollständig vorhanden, Quelle konnte aber nicht entfernt werden: {exc}", "warn")
            return False
