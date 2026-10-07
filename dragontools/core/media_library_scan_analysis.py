"""Prepare one filesystem/media snapshot without owning a database transaction."""
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ScanFileSnapshot:
    item: dict[str, Any] | None
    streams: list[dict[str, Any]]
    error: str = ""
    identity: tuple[int, int, int, int] | None = None


def analyze_scan_file(path, area, tools, analyzer, logger, item_mapper, fallback_mapper,
                      stream_mapper, sidecar_mapper, apply_context):
    identity = None
    try:
        stat = path.stat()
        identity = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
        info = analyzer(str(path), tools)
        item = item_mapper(path, info, source="storage_scan")
        streams = stream_mapper(path, info)
        error = ""
    except Exception as exc:
        error = f"Analyse fehlgeschlagen: {path.name}: {exc}"
        if logger:
            logger(f"Warnung: {path.name} konnte nicht analysiert werden: {exc}")
        if not path.is_file():
            return ScanFileSnapshot(None, [], error)
        item = fallback_mapper(path, source="storage_scan")
        streams = sidecar_mapper(path)
    try:
        stat = path.stat()
        current = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
    except OSError:
        current = None
    if current != identity:
        return ScanFileSnapshot(None, [], f"Quelldatei wurde während der Analyse geändert: {path}")
    apply_context(item, path, area)
    return ScanFileSnapshot(item, streams, error, identity)
