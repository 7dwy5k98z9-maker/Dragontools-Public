"""Conservative recovery of one replace intent bound to its original artifacts."""
from pathlib import Path

from .move_transaction import publish_staged_no_replace, remove_path
from .transaction_identity import renamed_receipt_matches, receipt_matches


def validated_replace_paths(data):
    if (data.get('format') != 'DragonToolsReplaceJournal'
            or data.get('format_version') != 1 or not data.get('active')):
        raise ValueError('Unbekanntes oder inaktives Replace-Journal.')
    paths = {}
    for key in ('source', 'destination', 'staging'):
        text = data.get(key)
        if not isinstance(text, str) or not text.strip() or not Path(text).is_absolute():
            raise ValueError('Replace-Journal enthält keinen absoluten Dateipfad.')
        paths[key] = Path(text)
        if paths[key].is_symlink():
            raise ValueError('Replace-Recovery folgt keinen Symlinks.')
    text = data.get('backup')
    paths['backup'] = Path(text) if text else None
    backup, destination = paths['backup'], paths['destination']
    if backup is not None and (backup.parent != destination.parent
            or not backup.name.startswith(destination.name + '.dragontools_backup')
            or backup.is_symlink()):
        raise ValueError('Replace-Backup passt nicht zum Transaktionsziel.')
    return paths


def _matches_new(data, path):
    return renamed_receipt_matches(path, data.get('staging_receipt'))


def recover_same_path(data, paths, totals):
    dest, stage, backup = paths['destination'], paths['staging'], paths['backup']
    status = str(data.get('status') or 'prepared')
    old = data.get('source_receipt')
    if backup is not None and backup.exists():
        if not renamed_receipt_matches(backup, old):
            return False
        if not dest.exists():
            publish_staged_no_replace(backup, dest)
            totals['restored'] += 1
            return True
        if not stage.exists() and _matches_new(data, dest):
            if status in {'committed', 'cleanup_pending'}:
                remove_path(backup)
                totals['completed'] += 1
            else:
                publish_staged_no_replace(dest, stage)
                publish_staged_no_replace(backup, dest)
                totals['restored'] += 1
            return True
        return False
    if dest.exists() and status in {'committed', 'cleanup_pending'} and _matches_new(data, dest):
        totals['completed'] += 1
        return True
    if (status in {'prepared', 'rolled_back'} and renamed_receipt_matches(dest, old)
            and _matches_new(data, stage)):
        totals['completed'] += 1
        return True
    return False


def recover_container_change(data, paths, totals):
    source, dest, stage = paths['source'], paths['destination'], paths['staging']
    status = str(data.get('status') or 'prepared')
    if dest.exists() and not stage.exists():
        if status not in {'committed', 'cleanup_pending'} or not _matches_new(data, dest):
            return False
        if source.exists():
            if not receipt_matches(source, data.get('source_receipt')):
                return False
            remove_path(source)
            totals['cleaned_sources'] += 1
        totals['completed'] += 1
        return True
    if (not dest.exists() and status in {'prepared', 'rolled_back'}
            and receipt_matches(source, data.get('source_receipt')) and _matches_new(data, stage)):
        totals['completed'] += 1
        return True
    return False


def recover_replace_intent(data, totals):
    paths = validated_replace_paths(data)
    mode = data.get('mode')
    if mode == 'same_path':
        if paths['source'] != paths['destination']:
            raise ValueError('Same-Path-Journal hat unterschiedliche Quell-/Zielpfade.')
        return recover_same_path(data, paths, totals)
    if mode == 'container_change':
        if len({paths['source'], paths['destination'], paths['staging']}) != 3:
            raise ValueError('Containerwechsel benötigt drei unterschiedliche Pfade.')
        return recover_container_change(data, paths, totals)
    return False
