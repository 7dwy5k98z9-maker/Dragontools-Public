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

from .move_transaction import PathSwapTransaction, PathTransactionRollbackError, publish_staged_no_replace
from .replace_journal import ReplaceJournal, ReplaceJournalWriteError
from .transaction_identity import receipt_matches, renamed_receipt_matches
from .journal_runtime import journal_transaction

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


@journal_transaction
def commit_staged_output(
    *,
    source: str | Path,
    staging: str | Path,
    destination: str | Path,
    log: LogFn,
    journal_root: str | Path | None = None,
    min_size: int = 1,
    remove_source: RemoveFn | None = None,
    abort_check: Callable[[], bool] | None = None,
    expected_source_receipt: dict | None = None,
    expected_staging_receipt: dict | None = None,
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
    _require_expected_receipt(source_path, expected_source_receipt, "Originalquelle")
    _require_expected_receipt(staging_path, expected_staging_receipt, "Geprüfte Ausgabe")

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
            abort_check=abort_check,
            expected_source_receipt=expected_source_receipt,
            expected_staging_receipt=expected_staging_receipt,
        )

    return _commit_container_change(
        source=source_path,
        staging=staging_path,
        destination=destination_path,
        log=log,
        journal_root=journal_root,
        remove_source=remove_source or os.remove,
        abort_check=abort_check,
        expected_source_receipt=expected_source_receipt,
        expected_staging_receipt=expected_staging_receipt,
    )


def _commit_same_path(
    *,
    source: Path,
    staging: Path,
    destination: Path,
    log: LogFn,
    journal_root: str | Path | None,
    abort_check: Callable[[], bool] | None = None,
    expected_source_receipt: dict | None = None,
    expected_staging_receipt: dict | None = None,
) -> OutputCommitResult:
    backup = unique_backup_path(destination)
    transaction = PathSwapTransaction(
        source=staging,
        destination=destination,
        backup_path=backup,
        staging_path=staging,
        preserve_staging_on_rollback=True,
        expected_destination_receipt=expected_source_receipt,
        expected_staging_receipt=expected_staging_receipt,
    )
    journal = ReplaceJournal.start(
        source=source,
        destination=destination,
        staging=staging,
        backup=backup,
        mode="same_path",
        root=journal_root,
        source_receipt=expected_source_receipt,
        staging_receipt=expected_staging_receipt,
    )

    try:
        _check_commit_abort(abort_check)
        transaction.commit(on_backup=lambda *_: _check_commit_abort(abort_check))
        journal.set_status("committed", fatal=True)
        if abort_check is not None and abort_check():
            raise RuntimeError("Abgebrochen vor Replace-Backup-Cleanup")
    except PathTransactionRollbackError as exc:
        journal.set_status("rollback_failed", message=str(exc))
        log(
            "Kritisch: Replace fehlgeschlagen und Rollback war unvollständig; "
            f"Altbestand-Backup bleibt erhalten: {exc.backup_path}",
            "error",
        )
        raise
    except Exception as operation_error:
        # A journal failure after installation is not a filesystem rollback.
        # Restore the actual original before reporting failure to the caller.
        if transaction.committed:
            try:
                if not renamed_receipt_matches(destination, transaction.installed_receipt):
                    raise OSError('Ausgabe wurde nach Commit verändert; Rollback verschiebt sie nicht.')
                publish_staged_no_replace(destination, staging)
                transaction.rollback()
            except OSError as rollback_error:
                log(f"Kritisch: Rollback unvollständig; Backup bleibt: {backup}", "error")
                raise PathTransactionRollbackError(operation_error, rollback_error, backup) from operation_error
        if source.exists() and not backup.exists():
            log(
                f"Rollback: Original wiederhergestellt nach fehlgeschlagenem Ersetzen: {source.name}",
                "warn",
            )
        try:
            journal.set_status("rolled_back", fatal=True)
        except OSError as journal_error:
            log(f"Rollback ausgeführt; Journal bleibt zur Prüfung erhalten: {journal_error}", "warn")
        else:
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
    abort_check: Callable[[], bool] | None = None,
    expected_source_receipt: dict | None = None,
    expected_staging_receipt: dict | None = None,
) -> OutputCommitResult:
    journal = ReplaceJournal.start(
        source=source,
        destination=destination,
        staging=staging,
        backup=None,
        mode="container_change",
        root=journal_root,
        source_receipt=expected_source_receipt,
        staging_receipt=expected_staging_receipt,
    )

    installed = False
    try:
        _check_commit_abort(abort_check)
        _require_expected_receipt(source, expected_source_receipt, "Originalquelle")
        if not receipt_matches(staging, journal.data['staging_receipt']):
            raise OSError('Video-Staging wurde nach der Prüfung verändert.')
        publish_staged_no_replace(staging, destination)
        installed = True
        # Erst ein *dauerhaft* geschriebenes "committed" darf spaeter die
        # Loeschung der Quelle autorisieren.  Ein Crash oder Datentraegerfehler
        # zwischen Rename und Journal-Update darf niemals dazu fuehren, dass die
        # Recovery nur aus der Existenz des Ziels auf einen Commit schliesst.
        journal.set_status("committed", fatal=True)
    except Exception as operation_error:
        if installed and destination.exists() and not staging.exists():
            if not renamed_receipt_matches(destination, journal.data['staging_receipt']):
                raise ReplaceJournalWriteError('Ausgabe wurde nach Commit verändert; bleibt zur Prüfung erhalten.') from operation_error
            try:
                publish_staged_no_replace(destination, staging)
            except OSError as rollback_error:
                log(
                    "Kritisch: Containerwechsel wurde sichtbar, konnte nach fehlgeschlagenem "
                    f"Commit-Journal aber nicht zurueckgerollt werden: {rollback_error}",
                    "error",
                )
                raise RuntimeError(
                    "Containerwechsel-Journal fehlgeschlagen und Dateisystem-Rollback war unvollstaendig. "
                    "Die Originalquelle wurde nicht geloescht."
                ) from operation_error
        # Wenn Quelle + Staging wieder vorhanden sind, ist nichts Destruktives
        # mehr aktiv.  Das Update ist best-effort; die Recovery behandelt ein
        # verbliebenes 'prepared'-Journal ebenfalls fail-closed.
        if source.exists() and staging.exists() and not destination.exists():
            journal.set_status("rolled_back")
            journal.finish()
        raise

    if abort_check is not None and abort_check():
        # The original still exists. Undo the install before cleanup can remove
        # it; the caller owns staging cleanup and sidecar rollback.
        if not renamed_receipt_matches(destination, journal.data['staging_receipt']):
            raise OSError('Ausgabe wurde nach Commit verändert; Abbruch verschiebt sie nicht.')
        publish_staged_no_replace(destination, staging)
        journal.set_status("rolled_back", fatal=True)
        journal.finish()
        raise RuntimeError("Abgebrochen vor Original-Cleanup")

    if source.resolve() != destination.resolve():
        try:
            if not receipt_matches(source, journal.data['source_receipt']):
                raise OSError('Originalquelle wurde vor dem Cleanup verändert; bleibt erhalten.')
            if not renamed_receipt_matches(destination, journal.data['staging_receipt']):
                raise OSError('Installierte Ausgabe wurde verändert; Original bleibt erhalten.')
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


def _check_commit_abort(abort_check) -> None:
    if abort_check is not None and abort_check():
        raise RuntimeError("Abgebrochen vor destruktivem Video-Commit")


def _require_expected_receipt(path, receipt, label):
    if receipt is not None and not receipt_matches(path, receipt):
        raise OSError(f'{label} wurde seit der Planung/Prüfung verändert; bleibt erhalten.')


__all__ = ["OutputCommitResult", "commit_staged_output", "unique_backup_path"]
