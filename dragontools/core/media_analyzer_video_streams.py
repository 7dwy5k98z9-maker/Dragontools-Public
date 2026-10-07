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
    first_metadata_text,
    infer_ffprobe_frame_rate_mode,
    normalize_video_codec,
    parse_bit_depth,
)
from .media_track_pairing import pair_media_tracks
from .models import VideoStream
from .media_analyzer_io import _ffmpeg_stream_index, _mi_bitrate, _warn_untrusted_stream_index
from .type_utils import _safe_int

_log = logging.getLogger(__name__)


def _stream_index(fp_stream: dict, fallback_index: int, warnings: list[str]) -> int:
    idx = _ffmpeg_stream_index(fp_stream, fallback_index)
    if idx < 0:
        _warn_untrusted_stream_index(
            warnings,
            stream_type="Video",
            ordinal=fallback_index,
        )
    return idx


def _first_positive_int(*values: object | None) -> int:
    for value in values:
        parsed = _safe_int(value, None)
        if parsed is not None and parsed > 0:
            return int(parsed)
    return 0


def _video_bitrate(mi_track: dict, fp_stream: dict, duration_s: float | None) -> int | None:
    fp_reported = _safe_int(fp_stream.get("bit_rate"), None)
    mi_reported = _mi_bitrate(mi_track)
    reported = next(
        (value for value in (fp_reported, mi_reported) if value is not None and value > 0),
        None,
    )
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

    # Beide Analysequellen werden zusammengeführt. MediaInfo ist die bevorzugte
    # Quelle für Container-/Formatstrings, ffprobe kann aber zusätzliche
    # Bitstream-Side-Data liefern. Ein vorhandener MediaInfo-Track darf deshalb
    # HDR10+/DV-Evidence aus ffprobe nicht mehr überschreiben.
    is_hdr = bool(mi_is_hdr or fp_is_hdr)
    has_hdr10plus = bool(mi_has_hdr10plus or fp_has_hdr10plus)

    mi_profile = None if mi_dv_profile in (None, "", "Ja") else str(mi_dv_profile)
    fp_profile = None if fp_dv_profile in (None, "", "Ja") else str(fp_dv_profile)
    if mi_profile and fp_profile and mi_profile.split(".", 1)[0] != fp_profile.split(".", 1)[0]:
        analysis_warnings.append(
            "[DV-Erkennung] MediaInfo und ffprobe melden unterschiedliche Profile "
            f"(MediaInfo={mi_profile}, ffprobe={fp_profile}); verwende ffprobe={fp_profile}."
        )
    if fp_profile:
        dv_profile = fp_profile
    elif mi_profile:
        dv_profile = mi_profile
    elif fp_dv_profile:
        dv_profile = fp_dv_profile
    else:
        dv_profile = mi_dv_profile

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
    for i, (mi_v, fp_v) in enumerate(pair_media_tracks(mi_videos, fp_videos, analysis_warnings)):

        idx = _stream_index(fp_v, i, analysis_warnings)
        codec = first_metadata_text(fp_v.get("codec_name"), mi_v.get("Format")) or ""
        width = _first_positive_int(mi_v.get("Width"), fp_v.get("width"))
        height = _first_positive_int(mi_v.get("Height"), fp_v.get("height"))
        pix_fmt = build_pix_fmt_from_mediainfo(mi_v) or first_metadata_text(fp_v.get("pix_fmt"))
        bit_depth = parse_bit_depth(mi_v, fp_v)

        color_space = first_metadata_text(
            mi_v.get("colour_space"), mi_v.get("ColorSpace"), fp_v.get("color_space")
        )
        color_transfer = first_metadata_text(
            mi_v.get("transfer_characteristics"),
            mi_v.get("TransferCharacteristics"),
            fp_v.get("color_transfer"),
        )
        color_primaries = first_metadata_text(
            mi_v.get("colour_primaries"),
            mi_v.get("colour_primaries_Source"),
            mi_v.get("ColorPrimaries"),
            fp_v.get("color_primaries"),
        )
        duration_s = _parse_mediainfo_duration_s(mi_v.get("Duration")) or _parse_seconds_value(fp_v.get("duration"))
        frame_count_value = _first_positive_int(
            mi_v.get("FrameCount"),
            fp_v.get("nb_read_frames"),
            fp_v.get("nb_frames"),
        )
        frame_count = frame_count_value or None
        frame_rate = _frame_rate_label(
            mi_v.get("FrameRate"),
            fp_v.get("avg_frame_rate"),
            fp_v.get("r_frame_rate"),
        )
        frame_rate_mode = _frame_rate_mode_label(
            mi_v.get("FrameRate_Mode"),
            mi_v.get("FrameRate_Mode/String"),
        ) or infer_ffprobe_frame_rate_mode(fp_v.get("avg_frame_rate"), fp_v.get("r_frame_rate"))
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
                profile=first_metadata_text(fp_v.get("profile"), mi_v.get("Format_Profile")),
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
