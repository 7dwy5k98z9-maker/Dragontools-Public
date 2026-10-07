"""Pure Hilfsfunktionen und gemeinsame Typen des Merge-Workers."""
from __future__ import annotations

from pathlib import Path
from typing import Any


class MergeUserAbortError(RuntimeError):
    """Interner Kontrollfluss für einen vom Benutzer ausgelösten Abbruch."""


def container_from_path(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix == ".mkv":
        return "mkv"
    if suffix in {".mp4", ".m4v"}:
        return "mp4"
    return suffix.lstrip(".") or "unknown"


def container_from_format_name(format_name: str) -> str:
    text = (format_name or "").lower()
    if "matroska" in text or "webm" in text:
        return "mkv"
    if "mov,mp4" in text or "mp4" in text or "ipod" in text:
        return "mp4"
    return "unknown"


def parse_fps(value: str | None) -> float | None:
    text = (value or "").strip()
    if not text or text in {"0/0", "0", "N/A"}:
        return None
    try:
        if "/" in text:
            numerator, denominator = text.split("/", 1)
            denominator_value = float(denominator)
            if denominator_value == 0:
                return None
            return round(float(numerator) / denominator_value, 6)
        return round(float(text), 6)
    except Exception:
        return None


def audio_signature(streams: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "codec": (stream.codec or "").lower(),
            "channels": int(stream.channels or 0),
            "language": (stream.language or "und").lower(),
        }
        for stream in streams
    ]


def subtitle_signature(streams: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "codec": (stream.codec or "").lower(),
            "language": (stream.language or "und").lower(),
            "forced": bool(stream.forced),
        }
        for stream in streams
    ]


def _stream_tag(stream: dict[str, Any], key: str) -> str:
    return str((stream.get("tags") or {}).get(key) or "").strip()


def _stream_disposition(stream: dict[str, Any], key: str) -> bool:
    return bool((stream.get("disposition") or {}).get(key, 0))


def video_probe_signature(streams: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Track-Header-Signatur fuer verlustfreies Matroska-Append.

    Attached pictures are intentionally excluded; they are not program video.
    Differences in codec private/profile, pixel format, HDR/color metadata, SAR
    or field order are unsafe to append under one Matroska track header.
    """
    result: list[dict[str, Any]] = []
    for stream in streams:
        if stream.get("codec_type") != "video" or _stream_disposition(stream, "attached_pic"):
            continue
        result.append({
            "codec": str(stream.get("codec_name") or "").lower(),
            "profile": str(stream.get("profile") or "").lower(),
            "codec_tag": str(stream.get("codec_tag_string") or "").lower(),
            "width": int(stream.get("width") or 0),
            "height": int(stream.get("height") or 0),
            "pix_fmt": str(stream.get("pix_fmt") or "").lower(),
            "sample_aspect_ratio": str(stream.get("sample_aspect_ratio") or "").lower(),
            "field_order": str(stream.get("field_order") or "").lower(),
            "color_space": str(stream.get("color_space") or "").lower(),
            "color_transfer": str(stream.get("color_transfer") or "").lower(),
            "color_primaries": str(stream.get("color_primaries") or "").lower(),
            "extradata": str(stream.get("extradata") or ""),
        })
    return result


def audio_probe_signature(streams: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for stream in streams:
        if stream.get("codec_type") != "audio":
            continue
        result.append({
            "codec": str(stream.get("codec_name") or "").lower(),
            "profile": str(stream.get("profile") or "").lower(),
            "extradata": str(stream.get("extradata") or ""),
            "sample_rate": int(stream.get("sample_rate") or 0),
            "channels": int(stream.get("channels") or 0),
            "channel_layout": str(stream.get("channel_layout") or "").lower(),
            "language": _stream_tag(stream, "language").lower() or "und",
            "title": _stream_tag(stream, "title"),
            "default": _stream_disposition(stream, "default"),
            "forced": _stream_disposition(stream, "forced"),
        })
    return result


def subtitle_probe_signature(streams: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for stream in streams:
        if stream.get("codec_type") != "subtitle":
            continue
        result.append({
            "codec": str(stream.get("codec_name") or "").lower(),
            "language": _stream_tag(stream, "language").lower() or "und",
            "title": _stream_tag(stream, "title"),
            "forced": _stream_disposition(stream, "forced"),
            "default": _stream_disposition(stream, "default"),
        })
    return result
