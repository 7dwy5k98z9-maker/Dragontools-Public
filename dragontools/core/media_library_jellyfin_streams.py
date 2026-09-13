from __future__ import annotations

import sqlite3
from typing import Any

from .media_library_db import _table_columns
from .media_library_jellyfin_source import _column_map, _row_value
from .media_library_utils import _bool, _float_or_none, _int_or_none, _normalize_stream_type

_HDR_MARKERS = (
    "hdr", "bt2020", "pq", "hlg", "dolby", "dovi", "dvhe", "smpte2084",
    "st2084", "arib-std-b67", "2094-40", "st2094",
)


def _is_stream_dict_type(stream: dict[str, Any], expected: str) -> bool:
    return _normalize_stream_type(
        stream.get("stream_type"), codec=stream.get("codec"), channels=stream.get("channels"),
        width=stream.get("width"), height=stream.get("height"),
    ).casefold() == expected.casefold()


def _video_flags_from_streams(
    streams: list[dict[str, Any]],
) -> tuple[int, int, int, str | None, int | None, int | None, str | None, int | None]:
    video = next((stream for stream in streams if _is_stream_dict_type(stream, "video")), {})
    text = " ".join(
        str(video.get(key) or "") for key in ("hdr_format", "codec", "pix_fmt", "title", "dv_profile")
    ).casefold()
    dv_profile = _int_or_none(video.get("dv_profile"))
    has_hdr10plus = int(
        _bool(video.get("hdr10plus_present"))
        or any(marker in text for marker in ("hdr10+", "hdr10plus", "dynamic metadata", "2094-40", "st2094"))
    )
    has_dv = int(
        _bool(video.get("rpu_present"))
        or (dv_profile is not None and dv_profile > 0)
        or any(marker in text for marker in ("dolby vision", "dovi", "dvhe", "dolbyvision"))
    )
    is_hdr = int(bool(has_hdr10plus or has_dv or any(marker in text for marker in _HDR_MARKERS)))
    return (
        is_hdr, has_hdr10plus, has_dv, video.get("dv_profile"), _int_or_none(video.get("width")),
        _int_or_none(video.get("height")), video.get("codec"), _int_or_none(video.get("bitrate")),
    )


def _jellyfin_hdr_format(row: sqlite3.Row, columns: dict[str, str]) -> str:
    parts: list[str] = []
    for name in (
        "VideoRange", "VideoRangeType", "ColorPrimaries", "ColorSpace", "ColorTransfer",
        "TransferCharacteristics", "HDR_Format", "HDR_Format_String", "HDR_Format_Commercial",
        "HDR_Format_Compatibility", "HdrFormat", "HdrFormatString",
    ):
        value = _row_value(row, columns, name, default=None)
        if value not in (None, ""):
            parts.append(str(value))
    for key, column in columns.items():
        normalized = key.replace("_", "").replace("-", "").casefold()
        if "hdr10plus" not in normalized and "hdr10+" not in normalized:
            continue
        value = row[column]
        text = str(value or "").strip().casefold()
        if _bool(value) or any(marker in text for marker in ("hdr10+", "hdr10plus", "2094-40", "true", "yes", "ja")):
            parts.append("hdr10plus")
    rpu_present = _bool(_row_value(row, columns, "RpuPresentFlag", default=0))
    dv_profile = _int_or_none(_row_value(row, columns, "DvProfile", "DolbyVisionProfile", default=None))
    if rpu_present or (dv_profile is not None and dv_profile > 0):
        parts.append("Dolby Vision")
    return " | ".join(dict.fromkeys(parts))


def _stream_from_jellyfin_row(row: sqlite3.Row, columns: dict[str, str]) -> dict[str, Any]:
    raw_stream_type = _row_value(row, columns, "StreamType", "type", default="")
    codec = _row_value(row, columns, "Codec", default=None)
    channels = _int_or_none(_row_value(row, columns, "Channels", default=None))
    width = _int_or_none(_row_value(row, columns, "Width", default=None))
    height = _int_or_none(_row_value(row, columns, "Height", default=None))
    stream_type = _normalize_stream_type(raw_stream_type, codec=codec, channels=channels, width=width, height=height)
    video_range = _jellyfin_hdr_format(row, columns)
    if stream_type.casefold() == "video" and not any(marker in video_range.casefold() for marker in _HDR_MARKERS):
        video_range = " | ".join(part for part in (video_range, "SDR") if part)
    average_frame_rate = _float_or_none(_row_value(row, columns, "AverageFrameRate", "AvgFrameRate", default=None))
    real_frame_rate = _float_or_none(_row_value(row, columns, "RealFrameRate", "FrameRate", default=None))
    frame_rate = average_frame_rate or real_frame_rate
    frame_rate_mode = None
    if average_frame_rate and real_frame_rate:
        frame_rate_mode = "CFR" if abs(average_frame_rate - real_frame_rate) <= 0.001 else "VFR"
    external_path = _row_value(row, columns, "Path", "ExternalPath", "FilePath", default=None)
    is_external_subtitle = stream_type.casefold() == "subtitle" and (
        _bool(_row_value(row, columns, "IsExternal", "External", "IsExternalSubtitle", default=0)) or bool(external_path)
    )
    return {
        "stream_type": stream_type,
        "stream_index": _int_or_none(_row_value(row, columns, "Index", "StreamIndex", default=None)),
        "codec": codec,
        "language": _row_value(row, columns, "Language", default=None),
        "forced": _bool(_row_value(row, columns, "IsForced", "IsForcedSubtitle", default=0)),
        "channels": channels,
        "channel_layout": _row_value(row, columns, "ChannelLayout", default=None),
        "bitrate": _int_or_none(_row_value(row, columns, "BitRate", "Bitrate", default=None)),
        "width": width, "height": height, "hdr_format": video_range,
        "dv_profile": _row_value(row, columns, "DvProfile", "DolbyVisionProfile", "Profile", default=None),
        "pix_fmt": _row_value(row, columns, "PixelFormat", "PixFmt", default=None),
        "bit_depth": _int_or_none(_row_value(row, columns, "BitDepth", default=None)),
        "profile": _row_value(row, columns, "Profile", default=None),
        "duration_s": None, "frame_count": None,
        "frame_rate": str(frame_rate) if frame_rate is not None else None,
        "frame_rate_mode": frame_rate_mode,
        "color_space": _row_value(row, columns, "ColorSpace", default=None),
        "color_transfer": _row_value(row, columns, "ColorTransfer", "TransferCharacteristics", default=None),
        "color_primaries": _row_value(row, columns, "ColorPrimaries", default=None),
        "source_kind": "external" if is_external_subtitle else "internal",
        "external_path": external_path if is_external_subtitle else None,
        "title": _row_value(row, columns, "Title", "DisplayTitle", default=None),
        "rpu_present": _bool(_row_value(row, columns, "RpuPresentFlag", default=0)),
        "hdr10plus_present": _bool(_row_value(row, columns, "Hdr10PlusPresentFlag", default=0)),
    }


def _trickplay_status_by_item(conn: sqlite3.Connection, table: str) -> dict[str, str]:
    columns = _table_columns(conn, table)
    item_col = columns.get("itemid") or columns.get("item_id") or columns.get("mediacontainerid")
    if not item_col:
        return {}
    cur = conn.execute(f"SELECT * FROM {table}")
    row_columns = _column_map(cur)
    statuses: dict[str, str] = {}
    for row in cur.fetchall():
        item_id = str(row[item_col] or "").casefold()
        if not item_id:
            continue
        count = _int_or_none(_row_value(row, row_columns, "ThumbnailCount", "Count", "ImageCount", default=None))
        status = "empty" if count is not None and count <= 0 else "present"
        if statuses.get(item_id) != "present":
            statuses[item_id] = status
    return statuses


def _group_streams_by_item(conn: sqlite3.Connection, table: str) -> dict[str, list[dict[str, Any]]]:
    columns = _table_columns(conn, table)
    item_col = columns.get("itemid") or columns.get("item_id") or columns.get("mediacontainerid")
    if not item_col:
        return {}
    cur = conn.execute(f"SELECT * FROM {table}")
    row_columns = _column_map(cur)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in cur.fetchall():
        item_id = str(row[item_col] or "").casefold()
        if item_id:
            grouped.setdefault(item_id, []).append(_stream_from_jellyfin_row(row, row_columns))
    return grouped
