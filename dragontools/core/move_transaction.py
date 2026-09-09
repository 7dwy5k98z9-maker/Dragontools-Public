# -*- coding: utf-8 -*-
"""Transaktionale Dateisystem-Bausteine fuer Move-/Replace-Workflows.

Das Modul ist absichtlich Qt-unabhaengig. Destruktive Pfadoperationen sollen
hier zentral getestet werden koennen, ohne ``MoveThread`` oder eine GUI laden
zu muessen.
"""
from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


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
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Kein freier Transaktionspfad gefunden fuer {dst.name}")


def copy_path_to_staging(source: str | Path, staging: str | Path) -> None:
    """Kopiert Quelle vollstaendig in einen noch nicht existierenden Staging-Pfad."""
    src = Path(source)
    stage = Path(staging)
    if src.is_dir() and not src.is_symlink():
        shutil.copytree(src, stage, copy_function=shutil.copy2, symlinks=True)
    else:
        stage.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, stage, follow_symlinks=False)


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

    def __post_init__(self) -> None:
        self.source = Path(self.source)
        self.destination = Path(self.destination)
        self.backup_path = Path(self.backup_path)
        if self.staging_path is not None:
            self.staging_path = Path(self.staging_path)

    def stage(self) -> Path:
        if self.staging_path is None:
            self.staging_path = unique_staging_path(self.destination)
        if self.staging_path.exists():
            raise FileExistsError(f"Staging-Pfad existiert bereits: {self.staging_path}")
        try:
            copy_path_to_staging(self.source, self.staging_path)
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

        if self.destination.exists() or self.destination.is_symlink():
            if self.backup_path.exists() or self.backup_path.is_symlink():
                raise FileExistsError(f"Backup-Pfad existiert bereits: {self.backup_path}")
            os.replace(str(self.destination), str(self.backup_path))
            self.backup_created = True

        try:
            if self.backup_created and on_backup is not None:
                on_backup(self.destination, self.backup_path)
            os.replace(str(stage), str(self.destination))
            self.committed = True
            self.staging_path = None
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
        os.replace(str(self.backup_path), str(self.destination))
        self.backup_created = False

    def cleanup_staging(self, *, best_effort: bool = False) -> None:
        stage = self.staging_path
        if stage is None or not (stage.exists() or stage.is_symlink()):
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
            remove_path(self.backup_path)
        self.backup_created = False
