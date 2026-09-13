from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .media_library_sidecars import _nfo_status_for_path, _subtitle_sidecar_streams, _trickplay_status_for_path
from .media_library_utils import _infer_item_type, _int_or_none, _normalize_title
from .models import MediaInfo

_LOG = logging.getLogger(__name__)


def _streams_from_media_info(info: MediaInfo) -> list[dict[str, Any]]:
    streams: list[dict[str, Any]] = []
    for idx, stream in enumerate(info.video_streams):
        streams.append(_video_stream_row(info, stream, idx))
    for idx, stream in enumerate(info.audio_streams):
        streams.append(_audio_stream_row(stream, idx))
    for idx, stream in enumerate(info.subtitle_streams):
        streams.append(_subtitle_stream_row(stream, idx))
    return streams


def _video_stream_row(info: MediaInfo, stream, index: int) -> dict[str, Any]:
    return {
        "stream_type": "Video",
        "stream_index": index,
        "codec": stream.codec,
        "language": None,
        "forced": 0,
        "channels": None,
        "channel_layout": None,
        "bitrate": stream.bitrate,
        "width": stream.width,
        "height": stream.height,
        "hdr_format": stream.hdr_format,
        "dv_profile": info.dolby_vision_profile,
        "pix_fmt": stream.pix_fmt,
        "bit_depth": stream.bit_depth,
        "profile": stream.profile,
        "duration_s": stream.duration_s,
        "frame_count": stream.frame_count,
        "frame_rate": stream.frame_rate,
        "frame_rate_mode": stream.frame_rate_mode,
        "color_space": stream.color_space,
        "color_transfer": stream.color_transfer,
        "color_primaries": stream.color_primaries,
        "source_kind": "internal",
        "external_path": None,
        "title": None,
    }


def _audio_stream_row(stream, index: int) -> dict[str, Any]:
    return {
        "stream_type": "Audio",
        "stream_index": index,
        "codec": stream.codec,
        "language": stream.language,
        "forced": 0,
        "channels": stream.channels,
        "channel_layout": stream.channel_layout,
        "bitrate": stream.bitrate,
        "width": None,
        "height": None,
        "hdr_format": None,
        "dv_profile": None,
        "pix_fmt": None,
        "bit_depth": None,
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
        "title": stream.title,
    }


def _subtitle_stream_row(stream, index: int) -> dict[str, Any]:
    return {
        "stream_type": "Subtitle",
        "stream_index": index,
        "codec": stream.codec,
        "language": stream.language,
        "forced": 1 if stream.forced else 0,
        "channels": None,
        "channel_layout": None,
        "bitrate": None,
        "width": None,
        "height": None,
        "hdr_format": None,
        "dv_profile": None,
        "pix_fmt": None,
        "bit_depth": None,
        "profile": None,
        "duration_s": stream.duration_s,
        "frame_count": None,
        "frame_rate": None,
        "frame_rate_mode": None,
        "color_space": None,
        "color_transfer": None,
        "color_primaries": None,
        "source_kind": getattr(stream, "source_kind", "internal") or "internal",
        "external_path": getattr(stream, "external_path", None),
        "title": stream.title,
    }


def _streams_from_media_info_with_sidecars(path: str | Path, info: MediaInfo) -> list[dict[str, Any]]:
    streams = _streams_from_media_info(info)
    max_index = max((_int_or_none(stream.get("stream_index")) or -1 for stream in streams), default=-1)
    streams.extend(_subtitle_sidecar_streams(path, max_index + 1))
    return streams


def _series_fields(file_path: Path, *, fallback_context: bool = False) -> tuple[str, str | None, Any, Any]:
    item_type = _infer_item_type("", str(file_path))
    series_title = None
    season = None
    episode = None
    try:
        from ..rules.move_rules import parse_series_match_details

        parsed = parse_series_match_details(str(file_path))
        if parsed:
            series_title = parsed.get("series")
            season = parsed.get("season")
            episode = parsed.get("episode")
            item_type = "episode"
    except Exception:
        suffix = " im Fallback-Pfad" if fallback_context else " aus dem Dateinamen"
        _LOG.warning(
            "Serienmetadaten konnten fuer %s%s nicht abgeleitet werden.",
            file_path,
            suffix,
            exc_info=True,
        )
    return item_type, series_title, season, episode


def _base_item(
    file_path: Path,
    *,
    source: str,
    item_type: str,
    series_title: str | None,
    season,
    episode,
    size_bytes: int | None,
) -> dict[str, Any]:
    title = file_path.stem
    return {
        "item_type": item_type,
        "title": title,
        "series_title": series_title,
        "season": season,
        "episode": episode,
        "year": None,
        "source": source,
        "source_id": None,
        "provider": None,
        "path": str(file_path),
        "parent_path": str(file_path.parent),
        "filename": file_path.name,
        "normalized_title": _normalize_title(series_title or title),
        "container": file_path.suffix.lstrip(".").lower(),
        "size_bytes": size_bytes,
        "nfo_status": _nfo_status_for_path(file_path),
        "trickplay_status": _trickplay_status_for_path(file_path),
        "exists_flag": 1,
        "active": 1,
    }


def _item_from_media_info(path: str | Path, info: MediaInfo, source: str = "dragontools") -> dict[str, Any]:
    file_path = Path(path)
    item_type, series_title, season, episode = _series_fields(file_path)
    video = info.video_streams[0] if info.video_streams else None
    try:
        size_bytes = int(file_path.stat().st_size)
    except OSError:
        size_bytes = _int_or_none(getattr(info, "size_bytes", None))

    item = _base_item(
        file_path,
        source=source,
        item_type=item_type,
        series_title=series_title,
        season=season,
        episode=episode,
        size_bytes=size_bytes,
    )
    item.update(
        {
            "duration_s": info.duration_s,
            "width": video.width if video else None,
            "height": video.height if video else None,
            "video_codec": video.codec if video else None,
            "video_bitrate": video.bitrate if video else None,
            "overall_bitrate": _average_bitrate(size_bytes, info.duration_s),
            "is_hdr": 1 if info.is_hdr else 0,
            "has_hdr10plus": 1 if info.has_hdr10plus else 0,
            "has_dolby_vision": 1 if info.dolby_vision else 0,
            "dv_profile": info.dolby_vision_profile,
            "analysis_status": "ok",
        }
    )
    return item


def _average_bitrate(size_bytes: int | None, duration_s: float | None) -> int | None:
    try:
        size = int(size_bytes or 0)
        duration = float(duration_s or 0.0)
    except (TypeError, ValueError):
        return None
    if size <= 0 or duration <= 0:
        return None
    return int(round((size * 8.0) / duration))


def _fallback_item_from_path(path: str | Path, source: str = "storage_scan") -> dict[str, Any]:
    """Minimaler DB-Eintrag, wenn MediaInfo/ffprobe eine Datei nicht analysieren kann."""
    file_path = Path(path)
    item_type, series_title, season, episode = _series_fields(file_path, fallback_context=True)
    try:
        size_bytes = file_path.stat().st_size
    except OSError:
        size_bytes = None

    item = _base_item(
        file_path,
        source=source,
        item_type=item_type,
        series_title=series_title,
        season=season,
        episode=episode,
        size_bytes=size_bytes,
    )
    item.update(
        {
            "duration_s": None,
            "width": None,
            "height": None,
            "video_codec": None,
            "video_bitrate": None,
            "overall_bitrate": None,
            "is_hdr": 0,
            "has_hdr10plus": 0,
            "has_dolby_vision": 0,
            "dv_profile": None,
            "analysis_status": "analysis_failed",
        }
    )
    return item
