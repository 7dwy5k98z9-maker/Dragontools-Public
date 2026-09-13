from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Any

from .media_library_utils import _int_or_none, _normalize_stream_type

_GERMAN_LANGUAGES = {"de", "deu", "ger", "german", "deutsch"}
_HDR_MARKERS = ("hdr", "bt2020", "pq", "hlg", "dolby", "smpte2084", "st2084")
_HDR10PLUS_MARKERS = ("hdr10+", "hdr10plus", "dynamic metadata", "2094-40", "st2094")
_DV_MARKERS = ("dolby vision", "dovi", "dvhe")


def _is_german(language: Any) -> bool:
    value = str(language or "").strip().casefold()
    return value in _GERMAN_LANGUAGES or value.startswith("de-")


def _stream_kind(row: sqlite3.Row | dict[str, Any]) -> str:
    return _normalize_stream_type(
        row["stream_type"],
        codec=row["codec"],
        channels=row["channels"],
        width=row["width"],
        height=row["height"],
    ).casefold()


def _has_marker(value: Any, markers: tuple[str, ...]) -> bool:
    text = str(value or "").casefold()
    return any(marker in text for marker in markers)


def _ordered_streams(streams: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    selected = [stream for stream in streams if stream.get("_kind") == kind]
    return sorted(
        selected,
        key=lambda row: (
            _int_or_none(row.get("stream_index")) if _int_or_none(row.get("stream_index")) is not None else 999999,
            _int_or_none(row.get("id")) or 0,
        ),
    )


def enrich_search_rows_with_streams(
    conn: sqlite3.Connection,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Populate display/search fields with one indexed stream query per result set."""
    media_ids = [int(row["_media_id"]) for row in rows if row.get("_media_id") is not None]
    if not media_ids:
        return rows

    streams_by_media: dict[int, list[dict[str, Any]]] = defaultdict(list)
    # SQLite defaults to 999 variables on older builds.  Chunk conservatively.
    for offset in range(0, len(media_ids), 400):
        chunk = media_ids[offset : offset + 400]
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
            stream["_kind"] = _stream_kind(stream)
            streams_by_media[int(stream["media_id"])].append(stream)

    for row in rows:
        media_id = int(row.pop("_media_id", 0) or 0)
        streams = streams_by_media.get(media_id, [])
        videos = _ordered_streams(streams, "video")
        audios = _ordered_streams(streams, "audio")
        subtitles = _ordered_streams(streams, "subtitle")
        first_video = videos[0] if videos else {}

        row["video_codec"] = str(row.get("video_codec") or first_video.get("codec") or "") or None
        row["width"] = _int_or_none(row.get("width")) or _int_or_none(first_video.get("width")) or 0
        row["height"] = _int_or_none(row.get("height")) or _int_or_none(first_video.get("height")) or 0

        stream_hdr = any(
            _has_marker(stream.get("hdr_format"), _HDR_MARKERS) or bool(str(stream.get("dv_profile") or "").strip())
            for stream in videos
        )
        stream_hdr10plus = any(_has_marker(stream.get("hdr_format"), _HDR10PLUS_MARKERS) for stream in videos)
        stream_dv = any(
            _has_marker(stream.get("hdr_format"), _DV_MARKERS) or bool(str(stream.get("dv_profile") or "").strip())
            for stream in videos
        )
        row["is_hdr"] = 1 if int(row.get("is_hdr") or 0) or stream_hdr else 0
        row["has_hdr10plus"] = 1 if int(row.get("has_hdr10plus") or 0) or stream_hdr10plus else 0
        row["has_dolby_vision"] = 1 if int(row.get("has_dolby_vision") or 0) or stream_dv else 0

        for key in (
            "profile",
            "pix_fmt",
            "bit_depth",
            "frame_rate",
            "frame_rate_mode",
            "frame_count",
            "color_space",
            "color_transfer",
            "color_primaries",
        ):
            target_key = "video_profile" if key == "profile" else key
            row[target_key] = first_video.get(key)

        row["has_german_audio"] = 1 if any(_is_german(stream.get("language")) for stream in audios) else 0
        row["audio_track_count"] = len(audios)
        row["audio_summary"] = ", ".join(
            f"{stream.get('language') or '?'}:{stream.get('codec') or '?'}" for stream in audios
        )
        row["audio_codecs"] = ",".join(str(stream.get("codec") or "?") for stream in audios)
        row["audio_channels"] = ",".join(str(stream.get("channels") or "?") for stream in audios)
        row["subtitle_summary"] = ", ".join(
            f"{stream.get('language') or '?'}:{stream.get('codec') or '?'}:"
            f"{'extern' if str(stream.get('source_kind') or 'internal').casefold() == 'external' else 'intern'}"
            for stream in subtitles
        )
        row["video_range"] = ",".join(str(stream.get("hdr_format") or "") for stream in videos)
    return rows
