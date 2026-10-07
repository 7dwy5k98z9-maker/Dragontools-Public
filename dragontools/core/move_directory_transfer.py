"""Directory planning, verified copy commit and source cleanup for MoveTransferExecutor."""
import errno
import shutil

from .move_conflicts import same_path
from .move_journal_contracts import MoveJournalWriteError
from .move_transaction import PathSwapTransaction, publish_staged_no_replace
from .transaction_identity import path_receipt, receipt_matches


def _record_proof(executor, source, source_receipt, destination_receipt):
    callback = getattr(executor.journal, 'set_commit_proof', None)
    if callable(callback):
        callback(source, source_receipt, destination_receipt)


def _cleanup_verified_copy(executor, source, dest, result, source_receipt):
    destination_receipt = path_receipt(dest)
    executor.check_abort()
    if not receipt_matches(source, source_receipt):
        raise OSError('Quellordner wurde nach der Kopierprüfung verändert; bleibt erhalten.')
    _record_proof(executor, source, source_receipt, destination_receipt)
    if not receipt_matches(dest, destination_receipt):
        raise OSError('Installierter Ordner wurde verändert; Quelle bleibt erhalten.')
    if not executor.remove_committed_source(source):
        message = 'Zielordner installiert; Quellordner konnte nicht entfernt werden.'
        result['cleanup_pending'] = True
        result['cleanup_message'] = message
        executor.journal.set_cleanup_pending(source, message)


def _replace_directory(executor, source, dest, result, mode):
    source_receipt = path_receipt(source)
    backup = executor.conflicts.unique_backup_path(dest)
    pairs = [{'original': str(dest), 'backup': str(backup), 'receipt': path_receipt(dest)}]
    transaction = PathSwapTransaction(source, dest, backup)
    try:
        transaction.stage()
        executor.check_abort()
        if not receipt_matches(source, source_receipt):
            raise OSError('Quellordner wurde nach der Kopierprüfung verändert.')
        executor.journal.set_backups(source, pairs)
        result['backup_pairs'] = list(pairs)
        result['transaction_backup_count'] = 1
        transaction.commit(on_backup=lambda *_: executor.check_abort())
        executor.conflicts.register_backup(backup)
        _cleanup_verified_copy(executor, source, dest, result, source_receipt)
        result['ok'] = True
        key = 'deleted_existing' if mode == 'delete_first' else 'replaced_existing'
        result[key] = True
        result[f'{key}_count'] = 1
        if not result.get('cleanup_pending'):
            executor.conflicts.discard(source, pairs, result)
        return True
    finally:
        transaction.cleanup_staging(best_effort=True)
        if not transaction.committed:
            executor.conflicts.rollback(source, pairs, result)


def _install_directory(executor, source, dest, result):
    source_receipt = path_receipt(source)
    # Same-volume rename keeps the verified inode and tree. Persist that intent
    # before the rename so its crash window can be recognized safely.
    _record_proof(executor, source, source_receipt, source_receipt)
    executor.check_abort()
    try:
        publish_staged_no_replace(source, dest)
    except OSError as exc:
        if exc.errno != errno.EXDEV and getattr(exc, 'winerror', None) != 17:
            raise
        transaction = PathSwapTransaction(source, dest,
            executor.conflicts.unique_backup_path(dest), replace_existing_destination=False)
        try:
            transaction.stage()
            executor.check_abort()
            if not receipt_matches(source, source_receipt):
                raise OSError('Quellordner wurde während des Kopierens verändert.')
            transaction.commit()
            _cleanup_verified_copy(executor, source, dest, result, source_receipt)
        finally:
            transaction.cleanup_staging(best_effort=True)
    executor.check_abort()
    result['ok'] = True
    result['dest_path'] = str(dest)
    return True


def move_directory(executor, source, dest, result, mode):
    try:
        executor.check_abort()
        if dest.exists() and same_path(source, dest):
            result['ok'] = True
            return True
        if dest.exists() or dest.is_symlink():
            result['conflict'] = True
            result['conflict_paths'] = [str(dest)]
            if mode == 'skip':
                result['skipped_conflict'] = True
                return False
            if mode in {'delete_first', 'overwrite'}:
                return _replace_directory(executor, source, dest, result, mode)
            if mode != 'rename':
                raise ValueError(f'Unbekannter Ordner-Konfliktmodus: {mode}')
            dest = executor.resolve_directory_rename_path(dest)
            result['renamed'] = True
            executor.journal.set_destination(source, dest)
        return _install_directory(executor, source, dest, result)
    except MoveJournalWriteError:
        raise
    except (OSError, shutil.Error, ValueError, RuntimeError) as exc:
        executor.log(f'Fehler beim Verschieben des Ordners: {exc}', 'error')
        result['ok'] = False
        return False
