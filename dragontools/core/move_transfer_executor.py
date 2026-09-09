# -*- coding: utf-8 -*-
"""Low-level rollback-safe file and directory transfer executor."""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Callable

from .move_journal import MoveJournalWriteError
from .move_transaction import PathSwapTransaction, PathTransactionRollbackError, remove_path
from .move_conflicts import same_path


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
        tmp_p = Path(str(dst_p) + ".__partial__")
        try:
            if tmp_p.exists():
                try:
                    tmp_p.unlink()
                except OSError as exc:
                    self.log(f"⚠️ Konnte temporäre Datei nicht entfernen: {tmp_p.name} – {exc}", "warn")
                    if backup_pairs:
                        self.conflicts.rollback(src_p, backup_pairs, result)
                    return False

            try:
                moved_size = src_p.stat().st_size
                os.link(str(src_p), str(dst_p))
                destination_installed = True
                self.notify_progress(hook, moved_size)
                return self.finish_installed_file(
                    src_p, dst_p, result, backup_pairs, replacement_mode=replacement_mode
                )
            except (OSError, FileExistsError):
                pass

            progress_hook = hook
            try:
                source_size = src_p.stat().st_size
                with open(src_p, "rb") as fsrc, open(tmp_p, "wb") as fdst:
                    while True:
                        self.wait()
                        if self.abort_immediately():
                            try:
                                tmp_p.unlink(missing_ok=True)
                            except OSError as cleanup_exc:
                                self.log(f"⚠️ Temporäre Datei konnte nicht gelöscht werden: {tmp_p.name} – {cleanup_exc}", "warn")
                            if backup_pairs:
                                self.conflicts.rollback(src_p, backup_pairs, result)
                            return False
                        buf = fsrc.read(8 * 1024 * 1024)
                        if not buf:
                            break
                        fdst.write(buf)
                        if progress_hook is not None and not self.notify_progress(progress_hook, len(buf)):
                            progress_hook = None
                    fdst.flush()
                    try:
                        os.fsync(fdst.fileno())
                    except OSError:
                        pass

                copied_size = tmp_p.stat().st_size
                if copied_size != source_size:
                    raise OSError(f"Größenprüfung fehlgeschlagen: Quelle={source_size} Byte, Kopie={copied_size} Byte")
                shutil.copystat(src_p, tmp_p)
                os.replace(str(tmp_p), str(dst_p))
                destination_installed = True
                return self.finish_installed_file(
                    src_p, dst_p, result, backup_pairs, replacement_mode=replacement_mode
                )
            except (OSError, shutil.Error) as exc:
                self.log(f"❌ Fehler beim Verschieben: {exc}", "error")
                try:
                    tmp_p.unlink(missing_ok=True)
                except OSError as cleanup_exc:
                    self.log(f"⚠️ Temporäre Datei konnte nicht gelöscht werden: {tmp_p.name} – {cleanup_exc}", "warn")
                if backup_pairs and not destination_installed:
                    self.conflicts.rollback(src_p, backup_pairs, result)
                return False
        except MoveJournalWriteError:
            if backup_pairs and not destination_installed:
                self.conflicts.rollback(src_p, backup_pairs, result)
            raise
        except Exception:
            if backup_pairs and not destination_installed:
                self.conflicts.rollback(src_p, backup_pairs, result)
            raise

    def move_directory(self, src_p: Path, dst_p: Path, result: dict, *, conflict_mode: str) -> bool:
        backup_pairs: list[dict[str, str]] = []
        destination_installed = False
        transaction: PathSwapTransaction | None = None
        try:
            if dst_p.exists() and same_path(src_p, dst_p):
                result["ok"] = True
                self.log(f"ℹ️ Ordner liegt bereits im Zielordner: {dst_p.name}", "info")
                return True

            if dst_p.exists():
                result["conflict"] = True
                result["conflict_paths"] = [str(dst_p)]
                if conflict_mode == "skip":
                    result["skipped_conflict"] = True
                    self.log(f"⚠️ Zielordner existiert bereits, übersprungen: {dst_p.name}", "warn")
                    return False
                if conflict_mode in {"delete_first", "overwrite"}:
                    backup_p = self.conflicts.unique_backup_path(dst_p)
                    backup_pairs = [{"original": str(dst_p), "backup": str(backup_p)}]
                    transaction = PathSwapTransaction(src_p, dst_p, backup_p)
                    transaction.stage()
                    self.journal.set_backups(src_p, backup_pairs)
                    result["backup_pairs"] = list(backup_pairs)
                    result["transaction_backup_count"] = 1
                    transaction.commit(
                        on_backup=lambda original, _backup: self.log(
                            f"🛡️ Vorhandener Ordner temporär gesichert: {original.name}", "info"
                        )
                    )
                    destination_installed = True
                    if not self.remove_committed_source(src_p):
                        message = "Zielordner installiert; Quellordner konnte nicht entfernt werden."
                        result["cleanup_pending"] = True
                        result["cleanup_message"] = message
                        self.journal.set_cleanup_pending(src_p, message)
                    result["ok"] = True
                    result["dest_path"] = str(dst_p)
                    key = "deleted_existing" if conflict_mode == "delete_first" else "replaced_existing"
                    result[key] = True
                    result[f"{key}_count"] = 1
                    self.conflicts.discard(src_p, backup_pairs, result)
                    return True
                if conflict_mode == "rename":
                    dst_p = self.resolve_directory_rename_path(dst_p)
                    result["renamed"] = True
                    result["dest_path"] = str(dst_p)
                    self.journal.set_destination(src_p, dst_p)
                    self.log(f"📝 Umbenennung: Zielordner heißt jetzt {dst_p.name}", "info")

            shutil.move(str(src_p), str(dst_p))
            result["ok"] = True
            result["dest_path"] = str(dst_p)
            return True
        except MoveJournalWriteError:
            if transaction is not None:
                transaction.cleanup_staging(best_effort=True)
            if backup_pairs and not destination_installed:
                self.conflicts.rollback(src_p, backup_pairs, result)
            raise
        except (OSError, shutil.Error, PathTransactionRollbackError, RuntimeError) as exc:
            self.log(f"❌ Fehler beim Verschieben des Ordners: {exc}", "error")
            if transaction is not None:
                transaction.cleanup_staging(best_effort=True)
            if backup_pairs and not destination_installed:
                self.conflicts.rollback(src_p, backup_pairs, result)
            return False

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
    ) -> bool:
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
