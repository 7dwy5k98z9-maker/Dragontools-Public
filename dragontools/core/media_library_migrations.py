from __future__ import annotations

import sqlite3

from .media_library_sqlite import _table_columns, _table_names
from .media_library_types import _now
from .media_library_utils import _normalize_title
from .path_syntax import path_compare_key


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
        "path_key": "TEXT NOT NULL DEFAULT ''",
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

    # Backfill stable host-independent identity keys.  Windows/UNC paths are
    # case-insensitive even when a database is inspected on Linux/CI; POSIX
    # paths keep their native case semantics through ``path_compare_key``.
    rows = conn.execute(
        "SELECT id, path, path_key, normalized_title, series_title, title, filename, "
        "active, exists_flag, updated_at FROM media_items ORDER BY id"
    ).fetchall()
    key_updates: list[tuple[str, int]] = []
    title_updates: list[tuple[str, int]] = []
    for row in rows:
        path = str(row["path"] or "")
        current_key = str(row["path_key"] or "")
        wanted_key = path_compare_key(path) if path else ""
        if wanted_key and current_key != wanted_key:
            key_updates.append((wanted_key, int(row["id"])))
        source_title = row["series_title"] or row["title"] or row["filename"] or ""
        normalized = _normalize_title(str(source_title))
        if normalized and str(row["normalized_title"] or "") != normalized:
            title_updates.append((normalized, int(row["id"])))
    if key_updates:
        conn.executemany("UPDATE media_items SET path_key=? WHERE id=?", key_updates)
    if title_updates:
        conn.executemany("UPDATE media_items SET normalized_title=? WHERE id=?", title_updates)

    # Older builds could persist the same Windows path with different casing.
    # Preserve every row, but keep only one logical copy active so current
    # lookups and replacement logic cannot act on duplicate active items.
    duplicate_keys = conn.execute(
        """
        SELECT path_key
          FROM media_items
         WHERE path_key<>'' AND active=1 AND exists_flag=1
         GROUP BY path_key
        HAVING COUNT(*)>1
        """
    ).fetchall()
    for duplicate in duplicate_keys:
        key = str(duplicate["path_key"] or "")
        candidates = conn.execute(
            """
            SELECT id
              FROM media_items
             WHERE path_key=? AND active=1 AND exists_flag=1
             ORDER BY coalesce(updated_at, '') DESC, id DESC
            """,
            (key,),
        ).fetchall()
        if len(candidates) > 1:
            stale_ids = [int(row["id"]) for row in candidates[1:]]
            placeholders = ",".join("?" for _ in stale_ids)
            conn.execute(
                f"UPDATE media_items SET active=0, updated_at=? WHERE id IN ({placeholders})",
                (_now(), *stale_ids),
            )

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
