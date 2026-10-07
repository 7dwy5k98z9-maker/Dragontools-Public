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
from .path_syntax import path_compare_key
from .media_library_analysis_merge import preserve_catalog_identity


def record_media_file(db_path: str | Path, file_path: str | Path, tools: Any = None) -> None:
    """Analysiert eine Datei und schreibt ihren aktuellen Snapshot in die Mediathek."""
    from .media_analyzer import analyze_media

    db = initialize_database(db_path)
    info = analyze_media(str(file_path), tools=tools)
    item = _item_from_media_info(file_path, info)
    streams = _streams_from_media_info_with_sidecars(file_path, info)
    with closing(_connect(db)) as conn:
        with conn:
            existing = conn.execute("SELECT * FROM media_items WHERE path_key=? AND active=1 AND exists_flag=1 ORDER BY id DESC LIMIT 1", (path_compare_key(str(file_path)),)).fetchone()
            if existing is not None:
                preserve_catalog_identity(item, existing)
                conn.execute("DELETE FROM nfo_metadata WHERE media_id=?", (existing['id'],))
                conn.execute("DELETE FROM nfo_provider_ids WHERE media_id=?", (existing['id'],))
                conn.execute("DELETE FROM nfo_issues WHERE media_id=?", (existing['id'],))
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
