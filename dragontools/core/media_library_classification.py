from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .media_library_utils import _int_or_none

def _resolution_bucket(width: Any, height: Any) -> str:
    """Classify common video resolutions while tolerating cinematic cropping."""
    w = _int_or_none(width) or 0
    h = _int_or_none(height) or 0
    if w <= 0 and h <= 0:
        return "unknown"
    if w >= 3000 or h >= 1800:
        return "uhd"
    if w >= 2300 or h >= 1300:
        return "qhd"
    if w >= 1600 or h >= 900:
        return "fhd"
    if w >= 1100 or h >= 650:
        return "hd"
    return "sd"


def _codec_bucket(codec: Any) -> str:
    value = str(codec or "").strip().casefold()
    if value in {"h264", "avc", "avc1"}:
        return "h264"
    if value in {"hevc", "h265", "h.265", "hev1", "hvc1"}:
        return "hevc"
    if value in {"av1", "av01"}:
        return "av1"
    return value or "unknown"


def _has_german_audio(row: dict[str, Any]) -> bool:
    return bool(row.get("has_german_audio"))


def _dynamic_range_bucket(row: dict[str, Any]) -> str:
    if row.get("has_dolby_vision"):
        return "dolby_vision"
    if row.get("has_hdr10plus"):
        return "hdr10plus"
    if row.get("is_hdr"):
        return "hdr"
    explicit_range = str(row.get("video_range") or "").casefold()
    analysis_status = str(row.get("analysis_status") or "").casefold()
    if "sdr" in explicit_range or analysis_status in {"ok", "jellyfin+scan"}:
        return "sdr"
    return "unknown"


def _audio_codec_signature(row: dict[str, Any]) -> str:
    codecs = {part.strip().casefold() for part in str(row.get("audio_codecs") or "").split(",") if part.strip()}
    return "+".join(sorted(codecs)) if codecs else "unknown"


def _audio_channels_signature(row: dict[str, Any]) -> str:
    channels = {part.strip() for part in str(row.get("audio_channels") or "").split(",") if part.strip()}
    return "+".join(sorted(channels)) if channels else "unknown"


def _deviation_value(row: dict[str, Any], criterion: str) -> str:
    if criterion == "german_audio":
        return "Deutsch vorhanden" if _has_german_audio(row) else "Deutsch fehlt"
    if criterion == "resolution":
        labels = {
            "sd": "< HD",
            "hd": "HD / 720p",
            "fhd": "Full HD / 1080p",
            "qhd": "QHD / 1440p",
            "uhd": "4K / UHD",
            "unknown": "Auflösung unbekannt",
        }
        return labels[_resolution_bucket(row.get("width"), row.get("height"))]
    if criterion == "video_codec":
        labels = {"h264": "H.264 / AVC", "hevc": "H.265 / HEVC", "av1": "AV1", "unknown": "Codec unbekannt"}
        bucket = _codec_bucket(row.get("video_codec"))
        return labels.get(bucket, str(row.get("video_codec") or "Codec unbekannt"))
    if criterion == "dynamic_range":
        labels = {
            "sdr": "SDR",
            "hdr": "HDR",
            "hdr10plus": "HDR10+",
            "dolby_vision": "Dolby Vision",
            "unknown": "HDR/SDR unbekannt",
        }
        return labels[_dynamic_range_bucket(row)]
    if criterion == "audio_codec":
        return _audio_codec_signature(row)
    if criterion == "audio_channels":
        return _audio_channels_signature(row)
    if criterion == "audio_track_count":
        return str(int(row.get("audio_track_count") or 0))
    return "unknown"


def _find_deviations(rows: list[dict[str, Any]], criterion: str, limit: int) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        parent = str(row.get("parent_path") or "").strip()
        if parent:
            groups[parent.casefold()].append(row)

    result: list[dict[str, Any]] = []
    for group_rows in groups.values():
        if len(group_rows) < 2:
            continue
        values = [_deviation_value(row, criterion) for row in group_rows]
        counts = Counter(values)
        if len(counts) < 2:
            continue

        dominant_value, dominant_count = counts.most_common(1)[0]
        total = len(group_rows)
        unique_dominant = dominant_count > total / 2

        if unique_dominant:
            for row, value in zip(group_rows, values):
                if value == dominant_value:
                    continue
                item = dict(row)
                item["deviation_reason"] = f"{value} – Mehrheit im Ordner: {dominant_value} ({dominant_count}/{total})"
                result.append(item)
        else:
            distribution = ", ".join(f"{value}: {count}" for value, count in counts.most_common())
            for row in group_rows:
                item = dict(row)
                item["deviation_reason"] = f"Uneinheitlich – keine klare Mehrheit ({distribution})"
                result.append(item)

        if len(result) >= limit:
            break

    result.sort(
        key=lambda row: (
            str(row.get("series_title") or row.get("title") or row.get("filename") or "").casefold(),
            row.get("season") if row.get("season") is not None else -1,
            row.get("episode") if row.get("episode") is not None else -1,
        )
    )
    return result[:limit]
