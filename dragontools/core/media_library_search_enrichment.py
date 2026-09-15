from __future__ import annotations

import sqlite3
from typing import Any

from .media_library_search_fields import enrich_row_with_streams, has_marker as _has_marker, is_german as _is_german
from .media_library_search_streams import load_streams_by_media, ordered_streams as _ordered_streams, stream_kind as _stream_kind


def enrich_search_rows_with_streams(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Populate display/search fields with one indexed stream query per result set."""
    media_ids = [int(row["_media_id"]) for row in rows if row.get("_media_id") is not None]
    if not media_ids:
        return rows
    streams_by_media = load_streams_by_media(conn, media_ids)
    for row in rows:
        media_id = int(row.pop("_media_id", 0) or 0)
        enrich_row_with_streams(row, streams_by_media.get(media_id, []))
    return rows


__all__ = ["enrich_search_rows_with_streams", "_is_german", "_stream_kind", "_has_marker", "_ordered_streams"]
