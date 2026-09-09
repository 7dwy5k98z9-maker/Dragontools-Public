# -*- coding: utf-8 -*-
"""Crash-robuster Commit bereits erzeugter Ausgabedateien.

Der Baustein ist Qt-unabhaengig und wird von Converter- und Hilfs-Workern
verwendet, damit destruktive Overwrite-Pfade nicht mehrfach implementiert sind.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .move_transaction import PathSwapTransaction, PathTransactionRollbackError
from .replace_journal import ReplaceJournal, ReplaceJournalWriteError

LogFn = Callable[[str, str], None]
RemoveFn = Callable[[str], None]


@dataclass(frozen=True)
class OutputCommitResult:
    destination: Path
    cleanup_pending: bool = False
    cleanup_message: str = ""
    backup_path: Path | None = None


def unique_backup_path(destination: str | Path) -> Path:
    path = Path(destination)
    base = path.with_name(f"{path.name}.dragontools_backup")
    if not base.exists():
        return base
    counter = 1
    while True:
        candidate = path.with_name(f"{path.name}.dragontools_backup_{counter}")
        if not candidate.exists():
            return candidate
        counter += 1


def commit_staged_output(
    *,
    source: str | Path,
    staging: str | Path,
    destination: str | Path,
    log: LogFn,
    journal_root: str | Path | None = None,
    min_size: int = 1,
    remove_source: RemoveFn | None = None,
) -> OutputCommitResult:
    """Installiert ``staging`` als ``destination`` und schuetzt ``source``.

    * Gleiches Quell-/Zielobjekt: Backup + ``PathSwapTransaction`` + Rollback.
    * Container-/Pfadwechsel: Commit wird vor dem Loeschen der Quelle durable
      journalisiert. Scheitert das anschliessende Quellen-Cleanup, bleibt das
      Journal fuer den Recovery-Lauf aktiv.

    ``staging`` muss bereits vollstaendig erzeugt sein und bleibt bei einem
    fehlgeschlagenen Same-Path-Commit erhalten, solange der Aufrufer es nicht
    anschliessend selbst bereinigt.
    """
    source_path = Path(source)
    staging_path = Path(staging)
    destination_path = Path(destination)
    min_size = max(1, int(min_size))

    if not staging_path.exists() or staging_path.stat().st_size < min_size:
        raise RuntimeError(
            f"Temporäre Ausgabedatei fehlt oder ist unplausibel klein: {staging_path.name}"
        )

    source_resolved = source_path.resolve()
    staging_resolved = staging_path.resolve()
    destination_resolved = destination_path.resolve()

    if destination_path.exists():
        if destination_resolved not in {source_resolved, staging_resolved}:
            raise RuntimeError(
                f"Zieldatei existiert bereits und wird nicht überschrieben: {destination_path.name}"
            )

    if destination_resolved == source_resolved:
        return _commit_same_path(
            source=source_path,
            staging=staging_path,
            destination=destination_path,
            log=log,
            journal_root=journal_root,
        )

    return _commit_container_change(
        source=source_path,
        staging=staging_path,
        destination=destination_path,
        log=log,
        journal_root=journal_root,
        remove_source=remove_source or os.remove,
    )


def _commit_same_path(
    *,
    source: Path,
    staging: Path,
    destination: Path,
    log: LogFn,
    journal_root: str | Path | None,
) -> OutputCommitResult:
    backup = unique_backup_path(destination)
    transaction = PathSwapTransaction(
        source=staging,
        destination=destination,
        backup_path=backup,
        staging_path=staging,
        preserve_staging_on_rollback=True,
    )
    journal = ReplaceJournal.start(
        source=source,
        destination=destination,
        staging=staging,
        backup=backup,
        mode="same_path",
        root=journal_root,
    )

    try:
        transaction.commit()
        journal.set_status("committed")
    except PathTransactionRollbackError as exc:
        journal.set_status("rollback_failed", message=str(exc))
        log(
            "Kritisch: Replace fehlgeschlagen und Rollback war unvollständig; "
            f"Altbestand-Backup bleibt erhalten: {exc.backup_path}",
            "error",
        )
        raise
    except (OSError, RuntimeError, ReplaceJournalWriteError):
        if source.exists() and not backup.exists():
            log(
                f"Rollback: Original wiederhergestellt nach fehlgeschlagenem Ersetzen: {source.name}",
                "warn",
            )
        journal.set_status("rolled_back")
        journal.finish()
        raise

    try:
        transaction.discard_backup()
    except OSError as exc:
        message = f"Replace-Backup konnte nicht gelöscht werden: {backup.name} - {exc}"
        journal.set_status("cleanup_pending", message=message)
        log(f"Warnung: {message}", "warn")
        return OutputCommitResult(
            destination=destination,
            cleanup_pending=True,
            cleanup_message=message,
            backup_path=backup,
        )

    journal.finish()
    return OutputCommitResult(destination=destination)


def _commit_container_change(
    *,
    source: Path,
    staging: Path,
    destination: Path,
    log: LogFn,
    journal_root: str | Path | None,
    remove_source: RemoveFn,
) -> OutputCommitResult:
    journal = ReplaceJournal.start(
        source=source,
        destination=destination,
        staging=staging,
        backup=None,
        mode="container_change",
        root=journal_root,
    )

    try:
        os.replace(str(staging), str(destination))
    except Exception:
        # Wenn der Commit sichtbar wurde, muss das Journal fuer Recovery aktiv
        # bleiben. Andernfalls ist noch nichts Destruktives geschehen.
        if not destination.exists() or staging.exists():
            journal.set_status("rolled_back")
            journal.finish()
        raise

    journal.set_status("committed")

    if source.resolve() != destination.resolve():
        try:
            remove_source(str(source))
            log(f"Original gelöscht (Containerwechsel): {source.name}", "info")
        except FileNotFoundError:
            pass
        except OSError as exc:
            message = (
                "Zieldatei ist installiert, Original konnte nach Containerwechsel nicht gelöscht werden: "
                f"{source.name} - {exc}"
            )
            journal.set_status("cleanup_pending", message=message)
            log(f"Warnung: {message}", "warn")
            return OutputCommitResult(
                destination=destination,
                cleanup_pending=True,
                cleanup_message=message,
            )

    journal.finish()
    return OutputCommitResult(destination=destination)


__all__ = ["OutputCommitResult", "commit_staged_output", "unique_backup_path"]
