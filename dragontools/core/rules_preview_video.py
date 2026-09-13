from __future__ import annotations

from typing import Any


def build_video_preview(mi) -> dict[str, Any]:
    pv = mi.primary_video
    if pv is None:
        return {
            "available": False,
            "codec": "",
            "width": None,
            "height": None,
            "bit_depth": None,
            "pix_fmt": None,
            "is_hdr": bool(getattr(mi, "is_hdr", False)),
            "has_dv": bool(getattr(mi, "has_dv", False)),
            "dv_profile": getattr(mi, "dv_profile", None) or getattr(mi, "dolby_vision_profile", None),
            "has_hdr10plus": bool(getattr(mi, "has_hdrplus", False)),
            "hdr_format": None,
        }
    return {
        "available": True,
        "index": pv.index,
        "codec": (pv.codec or "").lower(),
        "width": pv.width,
        "height": pv.height,
        "bit_depth": pv.bit_depth,
        "pix_fmt": pv.pix_fmt,
        "is_hdr": bool(getattr(mi, "is_hdr", False)),
        "has_dv": bool(getattr(mi, "has_dv", False)),
        "dv_profile": getattr(mi, "dv_profile", None) or getattr(mi, "dolby_vision_profile", None),
        "has_hdr10plus": bool(getattr(mi, "has_hdrplus", False)),
        "hdr_format": pv.hdr_format,
        "color_space": pv.color_space,
        "color_transfer": pv.color_transfer,
        "color_primaries": pv.color_primaries,
    }


def even_width_for_height(width: int, height: int, target_height: int) -> int:
    if width <= 0 or height <= 0 or target_height <= 0:
        return max(0, width)
    if target_height == height:
        return width
    scaled = width * target_height / height
    return max(2, int(round(scaled / 2.0)) * 2)


def build_target_video_preview(
    mi,
    ov: dict[str, Any],
    encoder_settings: dict[str, Any],
    *,
    autocrop_enabled: bool,
) -> dict[str, Any]:
    pv = mi.primary_video
    if pv is None or not pv.width or not pv.height:
        return {
            "width": None,
            "height": None,
            "resolution": "unbekannt",
            "scale_mode": str(encoder_settings.get("scale_mode") or "original"),
            "autocrop_pending": bool(autocrop_enabled),
        }
    source_width = int(pv.width)
    source_height = int(pv.height)
    strip_only = str(ov.get("processing_mode") or "").strip().lower() == "strip_only"
    scale_mode = str(encoder_settings.get("scale_mode") or "original").strip().lower()
    target_height = {"4k": 2160, "1080p": 1080, "720p": 720, "480p": 480}.get(scale_mode)
    if strip_only or target_height is None:
        out_height = source_height
        out_width = source_width
    else:
        out_height = min(source_height, target_height)
        out_width = even_width_for_height(source_width, source_height, out_height)
    return {
        "width": out_width,
        "height": out_height,
        "resolution": f"{out_width}x{out_height}",
        "scale_mode": scale_mode,
        "source_width": source_width,
        "source_height": source_height,
        "autocrop_pending": bool(autocrop_enabled and not strip_only),
        "strip_only": strip_only,
    }
