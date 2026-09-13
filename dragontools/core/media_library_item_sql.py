from __future__ import annotations

import sqlite3
from typing import Any

from .media_library_types import _now
from .media_library_utils import _normalize_stream_type

_ITEM_UPSERT_SQL = """
    INSERT INTO media_items(
        item_type, title, original_title, series_title, season, episode, year, source, source_id, provider,
        path, parent_path, filename, normalized_title, container, duration_s, size_bytes,
        width, height, video_codec, video_bitrate, overall_bitrate, is_hdr, has_hdr10plus,
        has_dolby_vision, dv_profile, nfo_status, nfo_path, nfo_type, nfo_mtime, nfo_scanned_at,
        trickplay_status, analysis_status, exists_flag, active, created_at, updated_at
    )
    VALUES(
        :item_type, :title, :original_title, :series_title, :season, :episode, :year, :source, :source_id,
        :provider, :path, :parent_path, :filename, :normalized_title, :container,
        :duration_s, :size_bytes, :width, :height, :video_codec, :video_bitrate,
        :overall_bitrate, :is_hdr, :has_hdr10plus, :has_dolby_vision, :dv_profile,
        :nfo_status, :nfo_path, :nfo_type, :nfo_mtime, :nfo_scanned_at, :trickplay_status,
        :analysis_status, :exists_flag, :active, :created_at, :updated_at
    )
    ON CONFLICT(path) DO UPDATE SET
        item_type=excluded.item_type,
        title=excluded.title,
        original_title=excluded.original_title,
        series_title=excluded.series_title,
        season=excluded.season,
        episode=excluded.episode,
        year=excluded.year,
        source=excluded.source,
        source_id=excluded.source_id,
        provider=excluded.provider,
        parent_path=excluded.parent_path,
        filename=excluded.filename,
        normalized_title=excluded.normalized_title,
        container=excluded.container,
        duration_s=excluded.duration_s,
        size_bytes=excluded.size_bytes,
        width=excluded.width,
        height=excluded.height,
        video_codec=excluded.video_codec,
        video_bitrate=excluded.video_bitrate,
        overall_bitrate=excluded.overall_bitrate,
        is_hdr=excluded.is_hdr,
        has_hdr10plus=excluded.has_hdr10plus,
        has_dolby_vision=excluded.has_dolby_vision,
        dv_profile=excluded.dv_profile,
        nfo_status=excluded.nfo_status,
        nfo_path=excluded.nfo_path,
        nfo_type=excluded.nfo_type,
        nfo_mtime=excluded.nfo_mtime,
        nfo_scanned_at=excluded.nfo_scanned_at,
        trickplay_status=excluded.trickplay_status,
        analysis_status=excluded.analysis_status,
        exists_flag=excluded.exists_flag,
        active=excluded.active,
        updated_at=excluded.updated_at
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

    conn.execute(_ITEM_UPSERT_SQL, row)
    media_id = int(conn.execute("SELECT id FROM media_items WHERE path=?", (row["path"],)).fetchone()["id"])
    conn.execute("DELETE FROM media_streams WHERE media_id=?", (media_id,))
    conn.executemany(
        _STREAM_INSERT_SQL,
        ({"media_id": media_id, **_prepare_stream_row(stream)} for stream in streams),
    )
    return media_id
