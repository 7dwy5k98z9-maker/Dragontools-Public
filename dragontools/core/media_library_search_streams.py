from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Any

from .media_library_utils import _int_or_none, _normalize_stream_type


def stream_kind(row: sqlite3.Row | dict[str, Any]) -> str:
    return _normalize_stream_type(
        row["stream_type"],
        codec=row["codec"],
        channels=row["channels"],
        width=row["width"],
        height=row["height"],
    ).casefold()


def ordered_streams(streams: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    selected = [stream for stream in streams if stream.get("_kind") == kind]
    return sorted(
        selected,
        key=lambda row: (
            _int_or_none(row.get("stream_index")) if _int_or_none(row.get("stream_index")) is not None else 999999,
            _int_or_none(row.get("id")) or 0,
        ),
    )


def load_streams_by_media(conn: sqlite3.Connection, media_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    streams_by_media: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for offset in range(0, len(media_ids), 400):
        chunk = media_ids[offset : offset + 400]
        if not chunk:
            continue
        placeholders = ",".join("?" for _ in chunk)
        stream_rows = conn.execute(
            f"""
            SELECT id, media_id, stream_type, stream_index, codec, language, channels,
                   width, height, hdr_format, dv_profile, pix_fmt, bit_depth, profile,
                   frame_rate, frame_rate_mode, frame_count, color_space,
                   color_transfer, color_primaries, source_kind
              FROM media_streams
             WHERE media_id IN ({placeholders})
             ORDER BY media_id, coalesce(stream_index, 999999), id
            """,
            chunk,
        ).fetchall()
        for stream_row in stream_rows:
            stream = dict(stream_row)
            stream["_kind"] = stream_kind(stream)
            streams_by_media[int(stream["media_id"])].append(stream)
    return streams_by_media


__all__ = ["stream_kind", "ordered_streams", "load_streams_by_media"]
