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
