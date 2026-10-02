from __future__ import annotations

from pathlib import Path

from .media_analyzer_metadata import VideoAnalysisMetadata
from .models import AudioStream, MediaInfo, SubtitleStream, VideoStream
from .type_utils import _safe_int
from .media_duration import source_duration


def build_media_info(
    *,
    path: str,
    mi_general: dict,
    ffprobe_json: dict,
    video_streams: list[VideoStream],
    audio_streams: list[AudioStream],
    subtitle_streams: list[SubtitleStream],
    metadata: VideoAnalysisMetadata,
    analysis_source: str,
    analysis_warnings: list[str],
) -> MediaInfo:
    format_data = ffprobe_json.get("format", {}) or {}
    duration_s = source_duration(
        ffprobe_json, video_streams=video_streams, audio_streams=audio_streams,
        container_duration=mi_general.get("Duration"),
    ) or 0.0
    size_bytes = _safe_int(
        mi_general.get("FileSize")
        or format_data.get("size")
        or (Path(path).stat().st_size if Path(path).exists() else 0),
        0,
    )
    dv_info = metadata.dv_info
    return MediaInfo(
        path=path,
        audio_streams=audio_streams,
        subtitle_streams=subtitle_streams,
        video_streams=video_streams,
        duration_s=duration_s,
        size_bytes=size_bytes,
        is_hdr=metadata.is_hdr,
        has_hdr10plus=metadata.has_hdr10plus,
        dolby_vision_profile=metadata.dolby_vision_profile_legacy,
        dolby_vision=dv_info["dolby_vision"],
        dv_profile=dv_info["dv_profile"],
        dv_profile_major=dv_info["dv_profile_major"],
        dv_codec_tag=dv_info["dv_codec_tag"],
        dv_level=dv_info["dv_level"],
        dv_format_raw=dv_info["dv_format_raw"],
        hdr_format_profile_raw=dv_info["hdr_format_profile_raw"],
        color_range=metadata.color_range,
        transfer_characteristics=metadata.transfer_characteristics,
        matrix_coefficients=metadata.matrix_coefficients,
        analysis_source=analysis_source,
        analysis_warnings=analysis_warnings,
    )
