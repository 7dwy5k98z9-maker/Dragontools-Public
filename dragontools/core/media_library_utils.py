from __future__ import annotations

from pathlib import Path
from typing import Any

from .paths import VIDEO_EXTENSIONS

_VIDEO_CODECS = {
    "h264", "avc", "avc1", "hevc", "h265", "h.265", "hev1", "hvc1", "av1", "av01",
    "mpeg1video", "mpeg2video", "mpeg4", "msmpeg4v2", "msmpeg4v3",
}
_AUDIO_CODECS = {
    "aac", "ac3", "a52", "eac3", "e-ac-3", "ec-3", "truehd", "mlp", "dts", "dca",
    "flac", "mp2", "mp3", "opus", "vorbis", "wmav2", "pcm_s16be", "pcm_s16le",
    "pcm_s24be", "pcm_s24le", "adpcm_ima_wav", "adpcm_ms",
}
_SUBTITLE_CODECS = {"subrip", "srt", "ass", "ssa", "pgssub", "dvbsub", "dvdsub", "mov_text", "xsub"}

def _bool(value: Any) -> int:
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return 1 if value else 0
    text = str(value or "").strip().casefold()
    return 1 if text in {"1", "true", "yes", "ja", "y"} else 0


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_title(value: str | None) -> str:
    import re
    import unicodedata

    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = re.sub(r"\(\d{4}\)", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _infer_item_type(type_text: str, path: str) -> str:
    text = (type_text or "").casefold()
    suffix = Path(path).suffix.casefold()
    if "episode" in text:
        return "episode"
    if "series" in text:
        return "series"
    if "season" in text:
        return "season"
    if "movie" in text or "film" in text:
        return "movie"
    if suffix in VIDEO_EXTENSIONS:
        try:
            from ..rules.move_rules import parse_series_match_details

            return "episode" if parse_series_match_details(path) else "movie"
        except Exception:
            return "video"
    return "folder"


def _safe_parent(path: str) -> str:
    try:
        return str(Path(path).parent)
    except Exception:
        return ""


def _normalize_stream_type(
    raw_type: Any,
    *,
    codec: Any = None,
    channels: Any = None,
    width: Any = None,
    height: Any = None,
) -> str:
    # Jellyfin serialisiert MediaStreamType als Integer. Dabei bedeutet 0
    # ausdrücklich Audio; ``raw_type or ""`` würde diesen Wert verlieren.
    text = str(raw_type if raw_type is not None else "").strip().casefold()
    codec_key = str(codec or "").strip().casefold()
    if text in {"video", "1"}:
        return "Video"
    if text in {"audio", "0"}:
        return "Audio"
    if text in {"subtitle", "subtitles", "2"}:
        return "Subtitle"
    if text in {"image", "embeddedimage", "attachment", "3"}:
        return "Image"
    if text in {"data", "4"}:
        return "Data"
    if _int_or_none(channels):
        return "Audio"
    if codec_key in _AUDIO_CODECS:
        return "Audio"
    if codec_key in _SUBTITLE_CODECS:
        return "Subtitle"
    if codec_key in _VIDEO_CODECS or ((_int_or_none(width) or 0) > 0 and (_int_or_none(height) or 0) > 0):
        return "Video"
    return str(raw_type or "").strip()
