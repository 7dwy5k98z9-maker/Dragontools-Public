from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .media_hdr_detection import detect_hdr_from_ffprobe_stream, parse_dolby_vision_profile
from .media_metadata import normalize_color_range_label, normalize_video_codec
from .models import VideoStream

_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class VideoAnalysisMetadata:
    is_hdr: bool
    has_hdr10plus: bool
    dolby_vision_profile_legacy: str | None
    dv_info: dict[str, Any]
    color_range: str | None
    transfer_characteristics: str | None
    matrix_coefficients: str | None


def _default_dv_info() -> dict[str, Any]:
    return {
        "dolby_vision": False,
        "dv_profile": None,
        "dv_profile_major": None,
        "dv_codec_tag": None,
        "dv_level": None,
        "dv_format_raw": None,
        "hdr_format_profile_raw": None,
    }


def _resolve_dv_info(
    video_streams: list[VideoStream],
    mi_videos: list[dict],
    fp_videos: list[dict],
) -> dict[str, Any]:
    dv_info = _default_dv_info()
    dv_streams = [stream for stream in video_streams if stream.hdr_format == "dolby_vision"]
    if not dv_streams or not mi_videos:
        return dv_info

    dv_info = parse_dolby_vision_profile(mi_videos[0])
    if not dv_info["dolby_vision"] or dv_info["dv_profile_major"] is None:
        if fp_videos:
            _, _, ffprobe_profile = detect_hdr_from_ffprobe_stream(fp_videos[0])
            if ffprobe_profile and ffprobe_profile != "Ja":
                try:
                    major = int(ffprobe_profile.split(".")[0])
                    dv_info["dolby_vision"] = True
                    dv_info["dv_profile"] = str(major)
                    dv_info["dv_profile_major"] = major
                except (ValueError, AttributeError):
                    dv_info["dolby_vision"] = True
            elif ffprobe_profile == "Ja":
                dv_info["dolby_vision"] = True
    if not dv_info["dolby_vision"]:
        dv_info["dolby_vision"] = True
    return dv_info


def _resolve_color_metadata(
    mi_videos: list[dict],
    fp_videos: list[dict],
) -> tuple[str | None, str | None, str | None]:
    if not mi_videos:
        return None, None, None

    media_info = mi_videos[0]
    ffprobe = fp_videos[0] if fp_videos else {}
    color_range = (
        media_info.get("colour_range")
        or media_info.get("ColorRange")
        or ffprobe.get("color_range")
        or None
    )
    transfer = (
        media_info.get("transfer_characteristics")
        or media_info.get("TransferCharacteristics")
        or ffprobe.get("color_transfer")
        or None
    )
    matrix = (
        media_info.get("matrix_coefficients")
        or media_info.get("MatrixCoefficients")
        or ffprobe.get("color_space")
        or None
    )
    return color_range, transfer, matrix


def collect_video_metadata(
    video_streams: list[VideoStream],
    mi_videos: list[dict],
    fp_videos: list[dict],
) -> VideoAnalysisMetadata:
    is_hdr = any(
        stream.hdr_format in {"hdr10", "hdr10plus", "dolby_vision"}
        for stream in video_streams
    )
    has_hdr10plus = any(
        stream.hdr_format == "hdr10plus" or getattr(stream, "has_hdr10plus", False)
        for stream in video_streams
    )
    dv_info = _resolve_dv_info(video_streams, mi_videos, fp_videos)
    legacy_profile = None
    if dv_info["dolby_vision"]:
        legacy_profile = dv_info["dv_profile"] or "Ja"
    color_range, transfer, matrix = _resolve_color_metadata(mi_videos, fp_videos)
    return VideoAnalysisMetadata(
        is_hdr=is_hdr,
        has_hdr10plus=has_hdr10plus,
        dolby_vision_profile_legacy=legacy_profile,
        dv_info=dv_info,
        color_range=color_range,
        transfer_characteristics=transfer,
        matrix_coefficients=matrix,
    )


def log_video_metadata(
    *,
    analysis_source: str,
    video_streams: list[VideoStream],
    metadata: VideoAnalysisMetadata,
) -> None:
    primary = video_streams[0] if video_streams else None
    dv_info = metadata.dv_info

    if dv_info["dolby_vision"]:
        if dv_info["dv_profile"] is not None and dv_info["dv_codec_tag"]:
            dv_label = f"Profil: {dv_info['dv_profile']} / {dv_info['dv_codec_tag']}"
        elif dv_info["dv_profile"] is not None:
            dv_label = f"Profil: {dv_info['dv_profile']}"
        else:
            dv_label = "Profil: unbekannt"
        color_info = (
            f"Range={normalize_color_range_label(metadata.color_range)} "
            f"(raw={metadata.color_range!r}) | "
            f"Transfer={metadata.transfer_characteristics or '?'} | "
            f"Matrix={metadata.matrix_coefficients or '?'}"
        )
        _log.info(
            "[MediaAnalyzer] Dolby Vision erkannt (%s) | Farb-Metadaten: %s",
            dv_label,
            color_info,
        )

    _log.info(
        "[MediaAnalyzer] Analyse abgeschlossen: "
        "analysis_source=%s codec=%s pix_fmt=%s bit_depth=%s "
        "color_transfer=%s color_primaries=%s hdr_format=%s "
        "has_hdr=%s has_hdr10plus=%s has_dolby_vision=%s dv_profile=%s dv_codec_tag=%s",
        analysis_source,
        normalize_video_codec(primary.codec if primary else None),
        primary.pix_fmt if primary else None,
        primary.bit_depth if primary else None,
        primary.color_transfer if primary else None,
        primary.color_primaries if primary else None,
        primary.hdr_format if primary else None,
        metadata.is_hdr,
        metadata.has_hdr10plus,
        dv_info["dolby_vision"],
        dv_info["dv_profile"],
        dv_info["dv_codec_tag"],
    )
