from __future__ import annotations

from typing import Any

from .media_library_search_streams import ordered_streams
from .media_library_utils import _int_or_none

_GERMAN_LANGUAGES = {"de", "deu", "ger", "german", "deutsch"}
_HDR_MARKERS = ("hdr", "bt2020", "pq", "hlg", "dolby", "smpte2084", "st2084")
_HDR10PLUS_MARKERS = (
    "hdr10+", "hdr10plus", "dynamic metadata", "2094-40", "st2094",
    "2094 app 4", "st 2094 app 4",
)
_DV_MARKERS = ("dolby vision", "dovi", "dvhe", "dvh1", "dva1", "dvav", "dav1")


def is_german(language: Any) -> bool:
    value = str(language or "").strip().casefold()
    return value in _GERMAN_LANGUAGES or value.startswith("de-")


def has_marker(value: Any, markers: tuple[str, ...]) -> bool:
    text = str(value or "").casefold()
    return any(marker in text for marker in markers)


def _enrich_video(row: dict[str, Any], videos: list[dict[str, Any]]) -> None:
    first = videos[0] if videos else {}
    row["video_codec"] = str(row.get("video_codec") or first.get("codec") or "") or None
    row["width"] = _int_or_none(row.get("width")) or _int_or_none(first.get("width")) or 0
    row["height"] = _int_or_none(row.get("height")) or _int_or_none(first.get("height")) or 0
    stream_hdr = any(has_marker(s.get("hdr_format"), _HDR_MARKERS) or bool(str(s.get("dv_profile") or "").strip()) for s in videos)
    stream_hdr10plus = any(has_marker(s.get("hdr_format"), _HDR10PLUS_MARKERS) for s in videos)
    stream_dv = any(has_marker(s.get("hdr_format"), _DV_MARKERS) or bool(str(s.get("dv_profile") or "").strip()) for s in videos)
    row["is_hdr"] = 1 if int(row.get("is_hdr") or 0) or stream_hdr else 0
    row["has_hdr10plus"] = 1 if int(row.get("has_hdr10plus") or 0) or stream_hdr10plus else 0
    row["has_dolby_vision"] = 1 if int(row.get("has_dolby_vision") or 0) or stream_dv else 0
    for key in ("profile", "pix_fmt", "bit_depth", "frame_rate", "frame_rate_mode", "frame_count", "color_space", "color_transfer", "color_primaries"):
        row["video_profile" if key == "profile" else key] = first.get(key)
    row["video_range"] = ",".join(str(stream.get("hdr_format") or "") for stream in videos)


def _enrich_audio(row: dict[str, Any], audios: list[dict[str, Any]]) -> None:
    row["has_german_audio"] = 1 if any(is_german(stream.get("language")) for stream in audios) else 0
    row["audio_track_count"] = len(audios)
    row["audio_summary"] = ", ".join(f"{s.get('language') or '?'}:{s.get('codec') or '?'}" for s in audios)
    row["audio_codecs"] = ",".join(str(s.get("codec") or "?") for s in audios)
    row["audio_channels"] = ",".join(str(s.get("channels") or "?") for s in audios)


def _enrich_subtitles(row: dict[str, Any], subtitles: list[dict[str, Any]]) -> None:
    row["subtitle_summary"] = ", ".join(
        f"{s.get('language') or '?'}:{s.get('codec') or '?'}:"
        f"{'extern' if str(s.get('source_kind') or 'internal').casefold() == 'external' else 'intern'}"
        for s in subtitles
    )


def enrich_row_with_streams(row: dict[str, Any], streams: list[dict[str, Any]]) -> dict[str, Any]:
    videos = ordered_streams(streams, "video")
    audios = ordered_streams(streams, "audio")
    subtitles = ordered_streams(streams, "subtitle")
    _enrich_video(row, videos)
    _enrich_audio(row, audios)
    _enrich_subtitles(row, subtitles)
    return row


__all__ = ["enrich_row_with_streams", "is_german", "has_marker"]
