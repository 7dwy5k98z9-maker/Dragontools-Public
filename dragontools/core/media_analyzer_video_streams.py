# -*- coding: utf-8 -*-
from __future__ import annotations

import logging

from .media_hdr_detection import (
    detect_hdr_from_ffprobe_stream,
    detect_hdr_from_mediainfo_track,
    validate_hdr_flags,
)
from .media_metadata import (
    _frame_rate_label,
    _frame_rate_mode_label,
    _parse_mediainfo_duration_s,
    _parse_seconds_value,
    build_pix_fmt_from_mediainfo,
    normalize_video_codec,
    parse_bit_depth,
)
from .models import VideoStream
from .media_analyzer_io import _mi_bitrate, _mi_stream_index
from .type_utils import _safe_int

_log = logging.getLogger(__name__)


def _stream_index(mi_track: dict, fp_stream: dict, fallback_index: int) -> int:
    idx = _safe_int(fp_stream.get("index"), None) if fp_stream else _mi_stream_index(mi_track, fallback_index)
    if idx is None:
        idx = _mi_stream_index(mi_track, fallback_index)
    return int(idx)


def _video_bitrate(mi_track: dict, fp_stream: dict, duration_s: float | None) -> int | None:
    reported = _safe_int(fp_stream.get("bit_rate"), 0) or (_mi_bitrate(mi_track) or 0) or None
    stream_size = _safe_int(mi_track.get("StreamSize"), 0)
    derived = (
        int(round((stream_size * 8.0) / duration_s))
        if stream_size and stream_size > 0 and duration_s and duration_s > 0
        else None
    )
    # Manche MKV-Dateien enthalten einen defekten BPS-Tag, den MediaInfo als
    # winzigen Videowert übernimmt. Streamgroesse/Dauer ist hier belastbarer.
    if derived and (not reported or reported < 10_000):
        return derived
    return reported


def _hdr_state(
    mi_track: dict,
    fp_stream: dict,
    *,
    codec: str,
    bit_depth: int | None,
    pix_fmt: str | None,
    analysis_warnings: list[str],
) -> tuple[str | None, bool, bool]:
    mi_is_hdr, mi_has_hdr10plus, mi_dv_profile = detect_hdr_from_mediainfo_track(mi_track)
    fp_is_hdr, fp_has_hdr10plus, fp_dv_profile = detect_hdr_from_ffprobe_stream(fp_stream)

    if mi_track:
        is_hdr, has_hdr10plus, dv_profile = mi_is_hdr, mi_has_hdr10plus, mi_dv_profile
        if not dv_profile and fp_dv_profile:
            dv_profile = fp_dv_profile
            is_hdr = is_hdr or fp_is_hdr
    else:
        is_hdr, has_hdr10plus, dv_profile = fp_is_hdr, fp_has_hdr10plus, fp_dv_profile

    is_hdr, has_hdr10plus, dv_profile = validate_hdr_flags(
        codec=codec,
        bit_depth=bit_depth,
        pix_fmt=pix_fmt,
        is_hdr=is_hdr,
        has_hdr10plus=has_hdr10plus,
        dv_profile=dv_profile,
        warnings=analysis_warnings,
    )

    if dv_profile:
        hdr_format = "dolby_vision"
    elif has_hdr10plus:
        hdr_format = "hdr10plus"
    elif is_hdr:
        hdr_format = "hdr10"
    else:
        hdr_format = None
    return hdr_format, has_hdr10plus, dv_profile is not None


def _build_video_streams(
    mi_videos: list[dict],
    fp_videos: list[dict],
    mi_json: dict,  # compatibility: intentionally not used for global HDR detection
    analysis_warnings: list[str],
) -> list[VideoStream]:
    del mi_json
    video_streams: list[VideoStream] = []
    for i in range(max(len(mi_videos), len(fp_videos))):
        mi_v = mi_videos[i] if i < len(mi_videos) else {}
        fp_v = fp_videos[i] if i < len(fp_videos) else {}

        idx = _stream_index(mi_v, fp_v, i)
        codec = fp_v.get("codec_name") or mi_v.get("Format") or ""
        width = _safe_int(mi_v.get("Width") or fp_v.get("width"), 0)
        height = _safe_int(mi_v.get("Height") or fp_v.get("height"), 0)
        pix_fmt = build_pix_fmt_from_mediainfo(mi_v) or fp_v.get("pix_fmt") or None
        bit_depth = parse_bit_depth(mi_v, fp_v)

        color_space = mi_v.get("colour_space") or mi_v.get("ColorSpace") or fp_v.get("color_space")
        color_transfer = (
            mi_v.get("transfer_characteristics")
            or mi_v.get("TransferCharacteristics")
            or fp_v.get("color_transfer")
        )
        color_primaries = (
            mi_v.get("colour_primaries")
            or mi_v.get("colour_primaries_Source")
            or mi_v.get("ColorPrimaries")
            or fp_v.get("color_primaries")
        )
        duration_s = _parse_mediainfo_duration_s(mi_v.get("Duration")) or _parse_seconds_value(fp_v.get("duration"))
        frame_count = (
            _safe_int(mi_v.get("FrameCount"), None)
            or _safe_int(fp_v.get("nb_read_frames"), None)
            or _safe_int(fp_v.get("nb_frames"), None)
        )
        frame_rate = _frame_rate_label(
            mi_v.get("FrameRate"),
            fp_v.get("avg_frame_rate"),
            fp_v.get("r_frame_rate"),
        )
        frame_rate_mode = _frame_rate_mode_label(
            mi_v.get("FrameRate_Mode"),
            mi_v.get("FrameRate_Mode/String"),
        )
        bitrate = _video_bitrate(mi_v, fp_v, duration_s)
        hdr_format, has_hdr10plus, has_dolby_vision = _hdr_state(
            mi_v,
            fp_v,
            codec=str(codec),
            bit_depth=bit_depth,
            pix_fmt=pix_fmt,
            analysis_warnings=analysis_warnings,
        )

        _log.debug(
            "[MediaAnalyzer] Video-Stream #%d: codec=%s pix_fmt=%s bit_depth=%s "
            "color_transfer=%s color_primaries=%s hdr_format=%s has_hdr10plus=%s has_dv=%s",
            i,
            normalize_video_codec(codec),
            pix_fmt,
            bit_depth,
            color_transfer,
            color_primaries,
            hdr_format,
            has_hdr10plus,
            has_dolby_vision,
        )

        video_streams.append(
            VideoStream(
                index=idx,
                codec=str(codec),
                width=width,
                height=height,
                hdr_format=hdr_format,
                has_hdr10plus=has_hdr10plus,
                has_dolby_vision=has_dolby_vision,
                profile=fp_v.get("profile") or mi_v.get("Format_Profile"),
                pix_fmt=pix_fmt,
                bit_depth=bit_depth,
                color_space=color_space,
                color_transfer=color_transfer,
                color_primaries=color_primaries,
                duration_s=duration_s,
                frame_count=frame_count,
                frame_rate=frame_rate,
                frame_rate_mode=frame_rate_mode,
                bitrate=bitrate,
            )
        )
    return video_streams
