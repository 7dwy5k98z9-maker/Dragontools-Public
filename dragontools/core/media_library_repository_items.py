from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Any

from .media_library_db import _connect, initialize_database
from .media_library_item_sql import _insert_item
from .media_library_media_info_mapper import (
    _average_bitrate,
    _fallback_item_from_path,
    _item_from_media_info,
    _streams_from_media_info,
    _streams_from_media_info_with_sidecars,
)
from .media_library_types import _now


def record_media_file(db_path: str | Path, file_path: str | Path, tools: Any = None) -> None:
    """Analysiert eine Datei und schreibt ihren aktuellen Snapshot in die Mediathek."""
    from .media_analyzer import analyze_media

    db = initialize_database(db_path)
    info = analyze_media(str(file_path), tools=tools)
    item = _item_from_media_info(file_path, info)
    streams = _streams_from_media_info_with_sidecars(file_path, info)
    with closing(_connect(db)) as conn:
        with conn:
            _insert_item(conn, item, streams)
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('updated_at', ?)", (_now(),))


__all__ = [
    "_average_bitrate",
    "_fallback_item_from_path",
    "_insert_item",
    "_item_from_media_info",
    "_streams_from_media_info",
    "_streams_from_media_info_with_sidecars",
    "record_media_file",
]
