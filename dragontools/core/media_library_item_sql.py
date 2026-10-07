from __future__ import annotations

import sqlite3
from typing import Any

from .media_library_types import _now
from .media_library_utils import _normalize_stream_type
from .path_syntax import path_compare_key

_ITEM_INSERT_SQL = """
    INSERT INTO media_items(
        item_type, title, original_title, series_title, season, episode, year, source, source_id, provider,
        path, path_key, parent_path, filename, normalized_title, container, duration_s, size_bytes,
        width, height, video_codec, video_bitrate, overall_bitrate, is_hdr, has_hdr10plus,
        has_dolby_vision, dv_profile, nfo_status, nfo_path, nfo_type, nfo_mtime, nfo_scanned_at,
        trickplay_status, analysis_status, exists_flag, active, created_at, updated_at
    )
    VALUES(
        :item_type, :title, :original_title, :series_title, :season, :episode, :year, :source, :source_id,
        :provider, :path, :path_key, :parent_path, :filename, :normalized_title, :container,
        :duration_s, :size_bytes, :width, :height, :video_codec, :video_bitrate,
        :overall_bitrate, :is_hdr, :has_hdr10plus, :has_dolby_vision, :dv_profile,
        :nfo_status, :nfo_path, :nfo_type, :nfo_mtime, :nfo_scanned_at, :trickplay_status,
        :analysis_status, :exists_flag, :active, :created_at, :updated_at
    )
"""

_ITEM_UPDATE_SQL = """
    UPDATE media_items SET
        item_type=:item_type,
        title=:title,
        original_title=:original_title,
        series_title=:series_title,
        season=:season,
        episode=:episode,
        year=:year,
        source=:source,
        source_id=:source_id,
        provider=:provider,
        parent_path=:parent_path,
        filename=:filename,
        normalized_title=:normalized_title,
        container=:container,
        duration_s=:duration_s,
        size_bytes=:size_bytes,
        width=:width,
        height=:height,
        video_codec=:video_codec,
        video_bitrate=:video_bitrate,
        overall_bitrate=:overall_bitrate,
        is_hdr=:is_hdr,
        has_hdr10plus=:has_hdr10plus,
        has_dolby_vision=:has_dolby_vision,
        dv_profile=:dv_profile,
        nfo_status=:nfo_status,
        nfo_path=:nfo_path,
        nfo_type=:nfo_type,
        nfo_mtime=:nfo_mtime,
        nfo_scanned_at=:nfo_scanned_at,
        trickplay_status=:trickplay_status,
        analysis_status=:analysis_status,
        exists_flag=:exists_flag,
        active=:active,
        updated_at=:updated_at
    WHERE id=:media_id
"""


_STREAM_INSERT_SQL = """
    INSERT INTO media_streams(
        media_id, stream_type, stream_index, codec, language, forced, channels,
        channel_layout, bitrate, width, height, hdr_format, dv_profile, pix_fmt,
        bit_depth, profile, duration_s, frame_count, frame_rate, frame_rate_mode,
        color_space, color_transfer, color_primaries, source_kind, external_path, title
    )
    VALUES(:media_id, :stream_type, :stream_index, :codec, :language, :forced, :channels,
        :channel_layout, :bitrate, :width, :height, :hdr_format, :dv_profile,
        :pix_fmt, :bit_depth, :profile, :duration_s, :frame_count, :frame_rate,
        :frame_rate_mode, :color_space, :color_transfer, :color_primaries,
        :source_kind, :external_path, :title)
"""

_STREAM_DEFAULTS = {
    "profile": None,
    "duration_s": None,
    "frame_count": None,
    "frame_rate": None,
    "frame_rate_mode": None,
    "color_space": None,
    "color_transfer": None,
    "color_primaries": None,
    "source_kind": "internal",
    "external_path": None,
}


def _prepare_stream_row(stream: dict[str, Any]) -> dict[str, Any]:
    row = dict(stream)
    for key, value in _STREAM_DEFAULTS.items():
        row.setdefault(key, value)
    row["stream_type"] = _normalize_stream_type(
        row.get("stream_type"),
        codec=row.get("codec"),
        channels=row.get("channels"),
        width=row.get("width"),
        height=row.get("height"),
    )
    return row


def _insert_item(conn: sqlite3.Connection, item: dict[str, Any], streams: list[dict[str, Any]]) -> int:
    """Upsertet ein Medienobjekt und ersetzt dessen Stream-Snapshot atomar."""
    now = _now()
    # Kompatibilität: der historische Repository-Helfer ergänzt die Zeit-/Defaultfelder
    # direkt im übergebenen Item-Dict. Einige interne Aufrufer könnten diesen Snapshot
    # nach dem Upsert weiterverwenden, daher bleibt diese Mutation bewusst erhalten.
    row = item
    row.setdefault("created_at", now)
    row["updated_at"] = now
    row.setdefault("exists_flag", 1)
    row.setdefault("active", row.get("exists_flag", 1))
    row.setdefault("original_title", None)
    row.setdefault("nfo_path", None)
    row.setdefault("nfo_type", None)
    row.setdefault("nfo_mtime", None)
    row.setdefault("nfo_scanned_at", None)
    row["path_key"] = path_compare_key(str(row.get("path") or ""))

    # Prefer the active logical identity over an exact but inactive legacy row.
    # This matters after schema migration: duplicate Windows spellings are kept
    # for audit/history but only one row remains active.  A rescan using an old
    # spelling must update that active row rather than re-activate the duplicate.
    lookup = None
    if row["path_key"]:
        lookup = conn.execute(
            "SELECT id FROM media_items WHERE path_key=? AND active=1 AND exists_flag=1 "
            "ORDER BY id DESC LIMIT 1",
            (row["path_key"],),
        ).fetchone()
    if lookup is None:
        lookup = conn.execute(
            "SELECT id FROM media_items WHERE path=? ORDER BY active DESC, exists_flag DESC, id DESC LIMIT 1",
            (row["path"],),
        ).fetchone()

    if lookup is not None:
        media_id = int(lookup["id"])
        conn.execute(_ITEM_UPDATE_SQL, {"media_id": media_id, **row})
    else:
        try:
            cursor = conn.execute(_ITEM_INSERT_SQL, row)
            media_id = int(cursor.lastrowid)
        except sqlite3.IntegrityError:
            # A concurrent writer may have published the same logical path
            # between the lookup and INSERT.  Resolve only that known race;
            # unrelated integrity failures remain visible.
            raced = None
            if row["path_key"]:
                raced = conn.execute(
                    "SELECT id FROM media_items WHERE path_key=? AND active=1 AND exists_flag=1 "
                    "ORDER BY id DESC LIMIT 1",
                    (row["path_key"],),
                ).fetchone()
            if raced is None:
                raced = conn.execute(
                    "SELECT id FROM media_items WHERE path=? ORDER BY active DESC, exists_flag DESC, id DESC LIMIT 1",
                    (row["path"],),
                ).fetchone()
            if raced is None:
                raise
            media_id = int(raced["id"])
            conn.execute(_ITEM_UPDATE_SQL, {"media_id": media_id, **row})
    conn.execute("DELETE FROM media_streams WHERE media_id=?", (media_id,))
    conn.executemany(
        _STREAM_INSERT_SQL,
        ({"media_id": media_id, **_prepare_stream_row(stream)} for stream in streams),
    )
    return media_id
