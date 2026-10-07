# -*- coding: utf-8 -*-
"""Transaktionale Dateisystem-Bausteine fuer Move-/Replace-Workflows.

Das Modul ist absichtlich Qt-unabhaengig. Destruktive Pfadoperationen sollen
hier zentral getestet werden koennen, ohne ``MoveThread`` oder eine GUI laden
zu muessen.
"""
from __future__ import annotations

import ctypes
import errno
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from copy import deepcopy
from .move_copy_verification import verify_staged_path_copy
from .transaction_identity import (object_identity, same_object, path_receipt,
    receipt_matches, renamed_receipt_matches)


class PathTransactionRollbackError(OSError):
    """Commit schlug fehl und auch das automatische Rollback war nicht vollstaendig."""

    def __init__(self, operation_error: Exception, rollback_error: Exception, backup_path: Path):
        self.operation_error = operation_error
        self.rollback_error = rollback_error
        self.backup_path = Path(backup_path)
        super().__init__(
            "Transaktion fehlgeschlagen und Altbestand konnte nicht automatisch "
            f"wiederhergestellt werden. Backup bleibt unter {self.backup_path}: "
            f"Commit={operation_error}; Rollback={rollback_error}"
        )


def remove_path(path: str | Path) -> None:
    """Entfernt Datei, Symlink oder Verzeichnis ohne dem Suffix zu vertrauen."""
    target = Path(path)
    if target.is_symlink() or not target.is_dir():
        target.unlink(missing_ok=True)
    else:
        shutil.rmtree(target)


def unique_staging_path(destination: str | Path, *, attempts: int = 1000) -> Path:
    """Erzeugt einen freien Staging-Pfad als Geschwister des Zielpfads."""
    dst = Path(destination)
    for _ in range(max(1, int(attempts))):
        token = uuid.uuid4().hex[:10]
        candidate = dst.with_name(f"{dst.name}.__dragontools_partial__{token}")
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
    raise RuntimeError(f"Kein freier Transaktionspfad gefunden fuer {dst.name}")




def publish_staged_no_replace(staging: str | Path, destination: str | Path) -> None:
    """Publish a fully staged sibling without overwriting a late destination.

    This is the commit primitive for moves that were planned against an absent
    destination.  A target that appears after conflict planning must never be
    silently replaced.  Windows ``os.rename`` already has no-replace semantics;
    Linux uses ``renameat2(RENAME_NOREPLACE)`` when available.  For regular files
    on other POSIX systems a hardlink provides the same atomic exclusion.
    """
    stage = Path(staging)
    dst = Path(destination)
    if not (stage.exists() or stage.is_symlink()):
        raise FileNotFoundError(f"Staging-Pfad fehlt: {stage}")
    if dst.exists() or dst.is_symlink():
        raise FileExistsError(f"Move-Ziel wurde zwischenzeitlich belegt: {dst}")

    if os.name == "nt":
        # On Windows os.rename() fails when dst already exists.
        os.rename(str(stage), str(dst))
        return

    if os.name == "posix" and hasattr(ctypes, "CDLL"):
        try:
            libc = ctypes.CDLL(None, use_errno=True)
            renameat2 = getattr(libc, "renameat2")
        except (OSError, AttributeError):
            renameat2 = None
        if renameat2 is not None:
            AT_FDCWD = -100
            RENAME_NOREPLACE = 1
            renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            renameat2.restype = ctypes.c_int
            rc = renameat2(
                AT_FDCWD, os.fsencode(stage), AT_FDCWD, os.fsencode(dst), RENAME_NOREPLACE
            )
            if rc == 0:
                return
            err = ctypes.get_errno()
            if err not in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP, getattr(errno, "EOPNOTSUPP", errno.ENOTSUP)}:
                if err == errno.EEXIST:
                    raise FileExistsError(err, os.strerror(err), str(dst))
                raise OSError(err, os.strerror(err), str(dst))

    # Portable POSIX fallback for files: hardlink creation is atomic and fails
    # with EEXIST instead of replacing a concurrently created target.
    if not stage.is_dir() or stage.is_symlink():
        os.link(str(stage), str(dst), follow_symlinks=False)
        remove_path(stage)
        return

    # Directory fallback for platforms without renameat2.  The project runtime
    # is Windows, where the branch above is atomic.  Keep the fallback fail-closed
    # for all ordinary late-conflict cases.
    if dst.exists() or dst.is_symlink():
        raise FileExistsError(f"Move-Ziel wurde zwischenzeitlich belegt: {dst}")
    os.rename(str(stage), str(dst))

def copy_file_to_staging(source, staging, *, follow_symlinks=False):
    src, stage = Path(source), Path(staging)
    if src.is_symlink() and not follow_symlinks:
        stage.symlink_to(os.readlink(src), target_is_directory=src.is_dir())
        return str(stage)
    identity = None
    try:
        with open(src, 'rb') as left, open(stage, 'xb') as right:
            identity = object_identity(stage)
            shutil.copyfileobj(left, right, 1024 * 1024)
            right.flush()
            os.fsync(right.fileno())
        shutil.copystat(src, stage, follow_symlinks=False)
        return str(stage)
    except Exception:
        # Exclusive creation owns only this inode; collisions never grant cleanup.
        if same_object(stage, identity):
            remove_path(stage)
        raise


def copy_path_to_staging(source: str | Path, staging: str | Path) -> None:
    """Kopiert Quelle vollstaendig in einen noch nicht existierenden Staging-Pfad."""
    src = Path(source)
    stage = Path(staging)
    if src.is_dir() and not src.is_symlink():
        stage.mkdir()
        identity = object_identity(stage)
        try:
            shutil.copytree(src, stage, copy_function=copy_file_to_staging,
                symlinks=True, dirs_exist_ok=True)
        except Exception:
            if same_object(stage, identity):
                remove_path(stage)
            raise
    else:
        stage.parent.mkdir(parents=True, exist_ok=True)
        copy_file_to_staging(src, stage, follow_symlinks=False)


@dataclass
class PathSwapTransaction:
    """Staged einen Pfad und ersetzt ein vorhandenes Ziel rollback-faehig.

    Ablauf:
      1. ``stage()`` kopiert die Quelle, ohne Quelle/Ziel zu veraendern.
      2. ``commit()`` benennt ein vorhandenes Ziel atomar auf ``backup_path`` um.
      3. Optionaler ``on_backup``-Callback kann diesen Zustand durable journalisieren.
      4. Staging wird atomar auf den Zielnamen committed.

    Schlaegt Schritt 3 oder 4 fehl, wird das Backup vor dem Weiterwerfen der
    Exception automatisch auf den Originalnamen zurueckgesetzt. Ein unerwarteter
    Callback-Fehler wird absichtlich nicht geschluckt: Rollback, dann Re-Raise.
    """

    source: Path
    destination: Path
    backup_path: Path
    staging_path: Path | None = None
    preserve_staging_on_rollback: bool = False
    backup_created: bool = False
    committed: bool = False
    replace_existing_destination: bool = True
    expected_destination_receipt: dict | None = None
    expected_staging_receipt: dict | None = None

    def __post_init__(self) -> None:
        self.source = Path(self.source)
        self.destination = Path(self.destination)
        self.backup_path = Path(self.backup_path)
        if self.staging_path is not None:
            self.staging_path = Path(self.staging_path)
        self._destination_receipt = path_receipt(self.destination) if self.destination.exists() or self.destination.is_symlink() else None
        self._staging_receipt = path_receipt(self.staging_path) if self.staging_path is not None and self.staging_path.exists() else None
        if self.expected_destination_receipt is not None:
            self._destination_receipt = deepcopy(self.expected_destination_receipt)
        if self.expected_staging_receipt is not None:
            self._staging_receipt = deepcopy(self.expected_staging_receipt)
        self._backup_receipt = None
        self.installed_receipt = None

    def stage(self) -> Path:
        if self.staging_path is None:
            self.staging_path = unique_staging_path(self.destination)
        if self.staging_path.exists() or self.staging_path.is_symlink():
            raise FileExistsError(f"Staging-Pfad existiert bereits: {self.staging_path}")
        source_receipt = path_receipt(self.source)
        try:
            copy_path_to_staging(self.source, self.staging_path)
            self._staging_receipt = path_receipt(self.staging_path)
            verify_staged_path_copy(self.source, self.staging_path)
            if not receipt_matches(self.source, source_receipt):
                raise OSError('Quelle wurde während des Kopierens ausgetauscht.')
        except (OSError, shutil.Error):
            self.cleanup_staging(best_effort=True)
            raise
        return self.staging_path

    def commit(
        self,
        *,
        on_backup: Callable[[Path, Path], None] | None = None,
    ) -> None:
        stage = self.staging_path
        if stage is None or not stage.exists():
            raise FileNotFoundError("Transaktions-Staging fehlt; stage() muss vor commit() erfolgreich sein.")
        if not receipt_matches(stage, self._staging_receipt):
            raise OSError('Transaktions-Staging wurde nach der Prüfung verändert.')

        if self.destination.exists() or self.destination.is_symlink():
            if not self.replace_existing_destination or not receipt_matches(self.destination, self._destination_receipt):
                raise FileExistsError(
                    f"Move-Ziel wurde zwischenzeitlich belegt: {self.destination}"
                )
            if self.backup_path.exists() or self.backup_path.is_symlink():
                raise FileExistsError(f"Backup-Pfad existiert bereits: {self.backup_path}")
            publish_staged_no_replace(self.destination, self.backup_path)
            self.backup_created = True
            self._backup_receipt = path_receipt(self.backup_path)

        try:
            if self.backup_created and not renamed_receipt_matches(self.backup_path, self._destination_receipt):
                raise OSError('Ziel wurde während der Backup-Übergabe verändert; Staging bleibt erhalten.')
            if self.backup_created and on_backup is not None:
                on_backup(self.destination, self.backup_path)
            publish_staged_no_replace(stage, self.destination)
            self.committed = True
            self.staging_path = None
            self.installed_receipt = path_receipt(self.destination)
        except Exception as operation_error:
            # Diese breite Grenze ist absichtlich: auch ein Programmier-/Callback-
            # Fehler nach dem Backup darf den Altbestand nicht unter falschem Namen
            # liegen lassen. Nach dem Rollback wird die Originalexception erneut
            # geworfen und damit nicht verschluckt.
            try:
                self.rollback()
            except (OSError, shutil.Error) as rollback_error:
                raise PathTransactionRollbackError(
                    operation_error,
                    rollback_error,
                    self.backup_path,
                ) from operation_error
            raise

    def rollback(self) -> None:
        """Stellt ein angelegtes Backup wieder her, sofern das Ziel noch frei ist.

        Bei caller-eigenem Staging (z. B. bereits vollständig erzeugter Output)
        kann ``preserve_staging_on_rollback`` gesetzt werden. Dann bleibt dieser
        Pfad bei einem fehlgeschlagenen Commit erhalten, während nur der
        Altbestand auf den Zielnamen zurückgerollt wird.
        """
        if not self.preserve_staging_on_rollback:
            self.cleanup_staging(best_effort=True)
        if not self.backup_created:
            return
        if not (self.backup_path.exists() or self.backup_path.is_symlink()):
            self.backup_created = False
            return
        if self.destination.exists() or self.destination.is_symlink():
            raise FileExistsError(
                f"Rollback nicht moeglich: Ziel existiert bereits: {self.destination}"
            )
        if not receipt_matches(self.backup_path, self._backup_receipt):
            raise OSError('Transaktions-Backup wurde verändert; bleibt erhalten.')
        publish_staged_no_replace(self.backup_path, self.destination)
        self.backup_created = False

    def cleanup_staging(self, *, best_effort: bool = False) -> None:
        stage = self.staging_path
        if stage is None or not (stage.exists() or stage.is_symlink()):
            return
        if not renamed_receipt_matches(stage, self._staging_receipt):
            return
        try:
            remove_path(stage)
            self.staging_path = None
        except (OSError, shutil.Error):
            if not best_effort:
                raise

    def discard_backup(self) -> None:
        """Loescht den Altbestand erst nach erfolgreichem Commit."""
        if not self.backup_created:
            return
        if self.backup_path.exists() or self.backup_path.is_symlink():
            if not receipt_matches(self.backup_path, self._backup_receipt):
                raise OSError('Transaktions-Backup wurde verändert; bleibt erhalten.')
            remove_path(self.backup_path)
        self.backup_created = False
