"""Recover sidecar records using their planned inode and full-content receipts."""
from pathlib import Path

from .move_transaction import publish_staged_no_replace
from .transaction_identity import renamed_receipt_matches


def validate_records(rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError('Sidecar-Journal enthält keinen Commit-Plan.')
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Sidecar-Plan enthält einen ungültigen Datensatz.')
        for key in ('source', 'destination'):
            text = row.get(key)
            if not isinstance(text, str) or not text.strip() or not Path(text).is_absolute():
                raise ValueError('Sidecar-Recovery benötigt absolute Dateipfade.')
        backup = row.get('backup')
        destination = Path(row['destination'])
        if backup and (Path(backup).parent != destination.parent
                or not Path(backup).name.startswith(destination.name + '.dragontools_backup')):
            raise ValueError('Sidecar-Backup passt nicht zum Transaktionsziel.')


def _paths(row):
    return Path(row['source']), Path(row['destination']), Path(row['backup']) if row.get('backup') else None


def rollback_records(rows):
    validate_records(rows)
    for row in reversed(rows):
        source, dest, backup = _paths(row)
        if source == dest or str(row.get('noop')) == '1':
            continue
        if not source.exists() and dest.exists():
            if not renamed_receipt_matches(dest, row.get('new_receipt')):
                raise OSError('Companion-Ziel ist kein verifiziertes Staging dieser Transaktion.')
            publish_staged_no_replace(dest, source)
        if backup is not None and backup.exists():
            if not renamed_receipt_matches(backup, row.get('old_receipt')):
                raise OSError('Companion-Backup wurde verändert; bleibt erhalten.')
            publish_staged_no_replace(backup, dest)


def complete_records(rows):
    validate_records(rows)
    for row in rows:
        source, dest, backup = _paths(row)
        if source == dest or str(row.get('noop')) == '1':
            if not renamed_receipt_matches(dest, row.get('new_receipt')):
                raise OSError('Companion am Ziel wurde verändert.')
            continue
        if not source.exists() and renamed_receipt_matches(dest, row.get('new_receipt')):
            continue
        if not renamed_receipt_matches(source, row.get('new_receipt')):
            raise OSError('Companion-Staging ist nicht mehr eindeutig vorhanden.')
        if dest.exists():
            if backup is None or not renamed_receipt_matches(dest, row.get('old_receipt')):
                raise OSError('Companion-Ziel wurde nach der Planung verändert.')
            publish_staged_no_replace(dest, backup)
        elif backup is not None and not renamed_receipt_matches(backup, row.get('old_receipt')):
            raise OSError('Erwartetes Companion-Backup ist nicht eindeutig vorhanden.')
        publish_staged_no_replace(source, dest)
