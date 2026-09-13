from __future__ import annotations

import sqlite3

from .media_library_sqlite import _table_columns, _table_names


def _ensure_media_items_schema(conn: sqlite3.Connection) -> None:
    columns = _table_columns(conn, "media_items") if "media_items" in _table_names(conn) else {}
    additions = {
        # Keep this list aligned with the current table definition. Legacy DBs
        # must become fully readable before current queries/indexes run.
        "item_type": "TEXT NOT NULL DEFAULT 'video'",
        "title": "TEXT",
        "original_title": "TEXT",
        "series_title": "TEXT",
        "season": "INTEGER",
        "episode": "INTEGER",
        "year": "INTEGER",
        "source": "TEXT",
        "source_id": "TEXT",
        "provider": "TEXT",
        "parent_path": "TEXT",
        "filename": "TEXT",
        "normalized_title": "TEXT",
        "container": "TEXT",
        "duration_s": "REAL",
        "size_bytes": "INTEGER",
        "width": "INTEGER",
        "height": "INTEGER",
        "video_codec": "TEXT",
        "video_bitrate": "INTEGER",
        "overall_bitrate": "INTEGER",
        "is_hdr": "INTEGER NOT NULL DEFAULT 0",
        "has_hdr10plus": "INTEGER NOT NULL DEFAULT 0",
        "has_dolby_vision": "INTEGER NOT NULL DEFAULT 0",
        "dv_profile": "TEXT",
        "nfo_status": "TEXT NOT NULL DEFAULT 'unknown'",
        "nfo_path": "TEXT",
        "nfo_type": "TEXT",
        "nfo_mtime": "REAL",
        "nfo_scanned_at": "TEXT",
        "trickplay_status": "TEXT NOT NULL DEFAULT 'unknown'",
        "analysis_status": "TEXT NOT NULL DEFAULT 'unknown'",
        "exists_flag": "INTEGER NOT NULL DEFAULT 1",
        "active": "INTEGER NOT NULL DEFAULT 1",
        "created_at": "TEXT NOT NULL DEFAULT ''",
        "updated_at": "TEXT NOT NULL DEFAULT ''",
    }
    for name, sql_type in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE media_items ADD COLUMN {name} {sql_type}")
    conn.execute("UPDATE media_items SET active=0 WHERE exists_flag=0")


def _ensure_media_streams_schema(conn: sqlite3.Connection) -> None:
    columns = _table_columns(conn, "media_streams") if "media_streams" in _table_names(conn) else {}
    additions = {
        "stream_type": "TEXT NOT NULL DEFAULT ''",
        "stream_index": "INTEGER",
        "codec": "TEXT",
        "language": "TEXT",
        "forced": "INTEGER NOT NULL DEFAULT 0",
        "channels": "INTEGER",
        "channel_layout": "TEXT",
        "bitrate": "INTEGER",
        "width": "INTEGER",
        "height": "INTEGER",
        "hdr_format": "TEXT",
        "dv_profile": "TEXT",
        "pix_fmt": "TEXT",
        "bit_depth": "INTEGER",
        "profile": "TEXT",
        "duration_s": "REAL",
        "frame_count": "INTEGER",
        "frame_rate": "TEXT",
        "frame_rate_mode": "TEXT",
        "color_space": "TEXT",
        "color_transfer": "TEXT",
        "color_primaries": "TEXT",
        "source_kind": "TEXT NOT NULL DEFAULT 'internal'",
        "external_path": "TEXT",
        "title": "TEXT",
    }
    for name, sql_type in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE media_streams ADD COLUMN {name} {sql_type}")
