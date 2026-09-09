# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass

from .media_analyzer_io import (
    _fp_streams_by_type,
    _mi_audio_tracks,
    _mi_general_track,
    _mi_text_tracks,
    _mi_video_tracks,
    _run_ffprobe_json,
    _run_mediainfo_json,
)
from .media_analyzer_metadata import collect_video_metadata, log_video_metadata
from .media_analyzer_result import build_media_info
from .media_analyzer_streams import (
    _build_audio_streams,
    _build_subtitle_streams,
    _build_video_streams,
)
from .media_hdr_detection import detect_hdr_from_mediainfo_track
from .media_metadata import build_pix_fmt_from_mediainfo
from .models import MediaInfo
from .paths import ToolPaths, get_tool_paths


@dataclass(frozen=True, slots=True)
class MediaInfoHdrInspection:
    """Ergebnis einer reinen MediaInfo-Prüfung dynamischer HDR-Metadaten."""

    available: bool
    video_found: bool
    dolby_vision: bool
    dolby_vision_profile: str | None
    hdr10plus: bool
    warnings: tuple[str, ...] = ()

    @property
    def conclusive(self) -> bool:
        return self.available and self.video_found


def inspect_dynamic_hdr_with_mediainfo(
    path: str,
    tools: ToolPaths | None = None,
) -> MediaInfoHdrInspection:
    """Prüft DV/HDR10+ ausschließlich über MediaInfo am fertigen Container."""
    resolved_tools = tools or get_tool_paths()
    payload, warnings, available = _run_mediainfo_json(path, resolved_tools)
    videos = _mi_video_tracks(payload) if payload else []
    if not available or not videos:
        return MediaInfoHdrInspection(
            available=available,
            video_found=bool(videos),
            dolby_vision=False,
            dolby_vision_profile=None,
            hdr10plus=False,
            warnings=tuple(warnings),
        )

    _is_hdr, has_hdr10plus, dv_profile = detect_hdr_from_mediainfo_track(videos[0])
    return MediaInfoHdrInspection(
        available=True,
        video_found=True,
        dolby_vision=dv_profile is not None,
        dolby_vision_profile=dv_profile,
        hdr10plus=bool(has_hdr10plus),
        warnings=tuple(warnings),
    )


def _analysis_payloads(
    path: str,
    tools: ToolPaths,
) -> tuple[dict, dict, str, list[str]]:
    warnings: list[str] = []
    media_info_json, media_info_warnings, media_info_found = _run_mediainfo_json(path, tools)
    warnings.extend(media_info_warnings)

    ffprobe_json, ffprobe_warnings = _run_ffprobe_json(path, tools)
    warnings.extend(ffprobe_warnings)
    if media_info_found and media_info_json:
        source = "MediaInfo.exe + ffprobe" if ffprobe_json else "MediaInfo.exe"
    elif ffprobe_json:
        source = (
            "MediaInfo versucht aber nicht gefunden, Fallback auf FFmpeg"
            if not media_info_found
            else "MediaInfo.exe (fehlgeschlagen), Fallback auf FFmpeg"
        )
    else:
        warnings.append("Keine Analysequelle erfolgreich: weder MediaInfo noch ffprobe lieferten Daten")
        source = "Unbekannt"
    return media_info_json, ffprobe_json, source, warnings


def analyze_media(path: str, tools: ToolPaths | None = None) -> MediaInfo:
    resolved_tools = tools or get_tool_paths()
    mi_json, fp_json, analysis_source, warnings = _analysis_payloads(path, resolved_tools)

    mi_general = _mi_general_track(mi_json)
    mi_videos = _mi_video_tracks(mi_json)
    mi_audios = _mi_audio_tracks(mi_json)
    mi_texts = _mi_text_tracks(mi_json)
    fp_videos = _fp_streams_by_type(fp_json, "video")
    fp_audios = _fp_streams_by_type(fp_json, "audio")
    fp_subtitles = _fp_streams_by_type(fp_json, "subtitle")

    video_streams = _build_video_streams(mi_videos, fp_videos, mi_json, warnings)
    audio_streams = _build_audio_streams(mi_audios, fp_audios)
    subtitle_streams = _build_subtitle_streams(mi_texts, fp_subtitles)
    metadata = collect_video_metadata(video_streams, mi_videos, fp_videos)
    log_video_metadata(
        analysis_source=analysis_source,
        video_streams=video_streams,
        metadata=metadata,
    )
    return build_media_info(
        path=path,
        mi_general=mi_general,
        ffprobe_json=fp_json,
        video_streams=video_streams,
        audio_streams=audio_streams,
        subtitle_streams=subtitle_streams,
        metadata=metadata,
        analysis_source=analysis_source,
        analysis_warnings=warnings,
    )
