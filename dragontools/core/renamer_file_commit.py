"""Filename-only video rename with rollback of its stem-bound companions."""
import os
from pathlib import Path
from .path_syntax import path_compare_key


def rename_prepared_file(source, target, *, discover_companions, publish, transaction_cls, journal_cls):
    source = Path(source)
    companions = [Path(path) for path in discover_companions(source)]
    transaction, journal = _commit_companions(source, target, companions, transaction_cls, journal_cls)
    try:
        if os.name == 'nt' and path_compare_key(source) == path_compare_key(target):
            # Windows permits spelling-only renames of the same path. os.rename
            # still refuses to replace a different destination object.
            os.rename(source, target)
        else:
            publish(source, target)
    except Exception as exc:
        if transaction is not None:
            try:
                transaction.rollback()
            except Exception as rollback_exc:
                raise RuntimeError('Video-Rename fehlgeschlagen und Begleitdateien konnten nicht vollständig '
                    f'zurückgerollt werden: rename={exc}; rollback={rollback_exc}') from exc
            journal.finish()
        raise
    if journal is not None:
        journal.finish()
    return target


def _commit_companions(source, target, companions, transaction_cls, journal_cls):
    if not companions:
        return None, None
    transaction = transaction_cls([str(path) for path in companions],
        source_base=source.with_suffix(''), destination_base=target.with_suffix(''))
    records = transaction.prepare_records()
    occupied = [row['destination'] for row in records if str(row.get('backup') or '')]
    if occupied:
        raise FileExistsError('Begleitdatei-Ziel existiert bereits: ' + ', '.join(Path(path).name for path in occupied))
    journal = journal_cls.start(video_staging=source, video_destination=target, records=records,
                                rename_only=True)
    try:
        transaction.commit()
        journal.set_status('sidecars_committed', fatal=False)
    except Exception:
        if all(Path(row['source']).exists() and not Path(row['destination']).exists() for row in records):
            journal.finish()
        raise
    return transaction, journal
