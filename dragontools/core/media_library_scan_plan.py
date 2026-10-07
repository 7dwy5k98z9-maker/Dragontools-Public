"""Spool analysis results before taking the library's writer transaction."""
from dataclasses import dataclass
from pathlib import Path
import json


@dataclass(frozen=True)
class ScanPlan:
    items: int
    streams: int
    failures: int
    aborted: bool


def prepare_scan(files, spool, prepare_file, warnings, progress=None, should_abort=None):
    items = streams = failures = 0
    aborted = source_changed = False
    for index, (path, area) in enumerate(files, start=1):
        if should_abort and should_abort():
            aborted = True
            break
        if progress:
            progress(index, len(files), str(path))
        prepared = prepare_file(path, area)
        if prepared.error:
            failures += 1
            warnings.append(prepared.error)
        if prepared.item is None:
            source_changed = True
            warnings.append(f"Scan-Kandidat wurde während des Scans geändert oder ist verschwunden: {path}")
            continue
        json.dump([str(path), area, prepared.item, prepared.streams, prepared.identity], spool, ensure_ascii=False)
        spool.write('\n')
        items += 1
        streams += len(prepared.streams)
    if should_abort and should_abort():
        aborted = True
    if not aborted and not source_changed:
        source_changed = not _sources_unchanged(spool)
    if source_changed:
        warnings.append("Mediathek-Scan nicht veröffentlicht: Quelldaten haben sich während des Scans geändert.")
    spool.seek(0)
    return ScanPlan(items, streams, failures, aborted or source_changed)


def iter_prepared_files(spool):
    for line in spool:
        path, area, item, streams, _identity = json.loads(line)
        yield Path(path), area, item, streams


def _sources_unchanged(spool):
    spool.seek(0)
    for line in spool:
        path, _area, _item, _streams, identity = json.loads(line)
        try:
            stat = Path(path).stat()
        except OSError:
            return False
        if [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns] != identity:
            return False
    return True
