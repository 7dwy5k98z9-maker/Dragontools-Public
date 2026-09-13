from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .media_library_jellyfin_source import (
    _infer_jellyfin_item_type,
    _is_importable_jellyfin_item,
    _jellyfin_duration_seconds,
    _jellyfin_item_id,
    _row_value,
)
from .media_library_jellyfin_streams import _video_flags_from_streams
from .media_library_paths import _matches_any_mapping_prefix, apply_path_mappings
from .media_library_repository import _item_from_media_info, _streams_from_media_info
from .media_library_types import PathMapping
from .media_library_utils import _int_or_none, _normalize_title, _safe_parent
from .paths import VIDEO_EXTENSIONS, path_compare_key


def build_jellyfin_item(
    row: sqlite3.Row,
    columns: dict[str, str],
    *,
    mappings: list[PathMapping],
    item_names_by_id: dict[str, str],
    streams_by_item: dict[str, list[dict[str, Any]]],
    trickplay_by_item: dict[str, str],
    has_trickplay_table: bool,
    seen_paths: set[str],
    analyze_existing_files: bool,
    tools: Any,
    warnings: list[str],
) -> tuple[dict[str, Any], list[dict[str, Any]], str] | None:
    raw_path = str(_row_value(row, columns, "Path", default="") or "")
    name = str(_row_value(row, columns, "Name", "OriginalTitle", "SortName", default="") or "")
    if not raw_path and not name:
        return None
    if raw_path and mappings and not _matches_any_mapping_prefix(raw_path, mappings):
        return None
    mapped_path = apply_path_mappings(raw_path, mappings) if raw_path else ""
    if not mapped_path:
        return None

    source_id = _jellyfin_item_id(row, columns)
    raw_type = str(_row_value(row, columns, "Type", "type", default="") or "")
    item_type = _infer_jellyfin_item_type(raw_type, mapped_path)
    if not _is_importable_jellyfin_item(item_type, mapped_path):
        return None
    path_key = path_compare_key(mapped_path)
    if path_key in seen_paths:
        return None
    seen_paths.add(path_key)

    streams = [dict(stream) for stream in streams_by_item.get(source_id, [])]
    for stream in streams:
        external_path = str(stream.get("external_path") or "").strip()
        if external_path and mappings:
            stream["external_path"] = apply_path_mappings(external_path, mappings)
    is_hdr, has_hdr10plus, has_dv, dv_profile, width, height, video_codec, video_bitrate = _video_flags_from_streams(streams)

    path_obj = Path(mapped_path)
    series_title = str(_row_value(row, columns, "SeriesName", default="") or "").strip()
    if item_type == "series":
        series_title = name or series_title
    elif not series_title:
        series_id = str(_row_value(row, columns, "SeriesId", default="") or "").casefold()
        series_title = item_names_by_id.get(series_id, "")

    season_field = "IndexNumber" if item_type == "season" else "ParentIndexNumber"
    season_number = _int_or_none(_row_value(row, columns, season_field, "SeasonNumber", default=None))
    size_bytes = _int_or_none(_row_value(row, columns, "Size", "FileSize", default=None))
    if not size_bytes or size_bytes <= 0:
        try:
            if path_obj.is_file():
                size_bytes = int(path_obj.stat().st_size)
        except OSError:
            pass

    item = {
        "item_type": item_type,
        "title": name or path_obj.stem,
        "original_title": str(_row_value(row, columns, "OriginalTitle", default="") or "").strip() or None,
        "series_title": series_title or None,
        "season": season_number,
        "episode": _int_or_none(_row_value(row, columns, "IndexNumber", "EpisodeNumber", default=None)) if item_type == "episode" else None,
        "year": _int_or_none(_row_value(row, columns, "ProductionYear", "PremiereDate", "Year", default=None)),
        "source": "jellyfin", "source_id": source_id or None, "provider": None,
        "path": mapped_path, "parent_path": _safe_parent(mapped_path), "filename": path_obj.name,
        "normalized_title": _normalize_title(series_title or name or path_obj.stem),
        "container": path_obj.suffix.lstrip(".").lower(),
        "duration_s": _jellyfin_duration_seconds(row, columns), "size_bytes": size_bytes,
        "width": width, "height": height, "video_codec": video_codec, "video_bitrate": video_bitrate,
        "overall_bitrate": _int_or_none(_row_value(row, columns, "TotalBitrate", "OverallBitrate", default=None)),
        "is_hdr": is_hdr, "has_hdr10plus": has_hdr10plus, "has_dolby_vision": has_dv, "dv_profile": dv_profile,
        "nfo_status": "unknown",
        "trickplay_status": trickplay_by_item.get(
            source_id,
            "missing" if has_trickplay_table and item_type in {"movie", "episode", "video"} else "unknown",
        ),
        "analysis_status": "jellyfin", "exists_flag": 1, "active": 1,
    }

    if analyze_existing_files and path_obj.suffix.casefold() in VIDEO_EXTENSIONS and path_obj.exists():
        try:
            from .media_analyzer import analyze_media
            info = analyze_media(str(path_obj), tools=tools)
            item.update(_item_from_media_info(path_obj, info, source="jellyfin+scan"))
            streams = _streams_from_media_info(info)
        except Exception as exc:
            warnings.append(f"Analyse fehlgeschlagen: {path_obj.name}: {exc}")
    return item, streams, source_id
