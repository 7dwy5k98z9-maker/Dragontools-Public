from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..core.lang_codes import canonical_lang
from ..core.media_metadata import normalize_video_codec
from .converter_utils import _parse_crop
from .hdr10_color import source_has_hdr10_base
from .media_contract_types import ExpectedAudioTrack, ExpectedMediaContract, ExpectedSubtitleTrack


def _build_audio_tracks(media_info, file_override, container, *, audio_planner, audio_codec_family):
    plan = audio_planner(
        audio_streams=list(getattr(media_info, "audio_streams", []) or []),
        file_override=file_override,
        container=container,
    )
    return tuple(
        ExpectedAudioTrack(
            codec=audio_codec_family(decision.target_codec),
            channels=max(0, int(decision.target_channels or 0)),
            language=canonical_lang(getattr(decision.stream, "language", None)),
        )
        for decision in plan
    )


def _internal_subtitles(
    media_info,
    file_override,
    container,
    strip_only,
    subtitle_rules,
    *,
    subtitle_planner,
    mp4_storage_planner,
):
    plan = subtitle_planner(
        list(getattr(media_info, "subtitle_streams", []) or []),
        audio_streams=list(getattr(media_info, "audio_streams", []) or []),
        file_override=file_override,
        subtitle_rules=subtitle_rules,
        container_copy_supported=True,
        media_duration_s=getattr(media_info, "duration_s", None),
    )
    target_container = str(container or "").lower()
    if target_container == "mp4":
        return list(
            mp4_storage_planner(
                plan,
                subtitle_rules=subtitle_rules,
                preserve_burn_candidate=bool(strip_only),
            ).internal_streams
        )
    if not strip_only:
        return list(plan.keep_streams)

    candidates = ([plan.burn_sub] if plan.burn_sub is not None else []) + list(plan.keep_streams)
    seen: set[int] = set()
    streams = []
    for stream in candidates:
        index = int(stream.index)
        if index not in seen:
            seen.add(index)
            streams.append(stream)
    return streams


def _build_subtitle_tracks(
    media_info,
    file_override,
    container,
    strip_only,
    subtitle_rules,
    *,
    subtitle_planner,
    mp4_storage_planner,
    subtitle_codec_family,
):
    target_container = str(container or "").lower()
    streams = _internal_subtitles(
        media_info,
        file_override,
        container,
        strip_only,
        subtitle_rules,
        subtitle_planner=subtitle_planner,
        mp4_storage_planner=mp4_storage_planner,
    )
    return tuple(
        ExpectedSubtitleTrack(
            codec="mov_text" if target_container == "mp4" else subtitle_codec_family(getattr(stream, "codec", "")),
            language=canonical_lang(getattr(stream, "language", None)),
            forced=bool(getattr(stream, "forced", False)),
        )
        for stream in streams
    )


def _expected_dimensions(media_info, strip_only: bool, scale_mode: str | None, crop_filter: str | None):
    primary = getattr(media_info, "primary_video", None)
    source_width = int(getattr(primary, "width", 0) or 0)
    source_height = int(getattr(primary, "height", 0) or 0)
    crop = _parse_crop(crop_filter)
    mode = str(scale_mode or "original").strip().lower()

    if strip_only:
        return source_width or None, source_height or None
    if mode in {"1080p", "720p", "480p", "4k"}:
        target_height = {"1080p": 1080, "720p": 720, "480p": 480, "4k": 2160}[mode]
        effective_height = int(crop[1]) if crop is not None else source_height
        return None, min(target_height, effective_height) if effective_height > 0 else target_height
    if mode in {"", "original", "originale auflösung", "originalauflösung"}:
        if crop is not None:
            return int(crop[0]), int(crop[1])
        return source_width or None, source_height or None
    return None, None


def _video_requirements(
    media_info,
    *,
    pipeline: str,
    strip_only: bool,
    target_codec: str,
    effective_preserve_hdrplus: bool,
):
    primary = getattr(media_info, "primary_video", None)
    source_has_dv = bool(getattr(media_info, "has_dv", False))
    source_has_hdr10plus = bool(
        getattr(media_info, "has_hdrplus", False)
        or getattr(media_info, "has_hdr10plus", False)
    )
    if strip_only:
        require_dv = source_has_dv
        require_hdr10plus = source_has_hdr10plus
        require_hdr = bool(getattr(media_info, "is_hdr", False)) or require_dv or require_hdr10plus
        source_depth = getattr(primary, "bit_depth", None)
        return require_hdr, require_dv, require_hdr10plus, int(source_depth) if source_depth else None

    pipeline_name = str(getattr(pipeline, "value", pipeline) or "").strip().lower()
    require_dv = pipeline_name in {"dv", "av1_dv"}
    require_hdr10plus = pipeline_name in {"hdrplus", "av1_hdrplus"} or (
        pipeline_name == "dv" and source_has_hdr10plus and bool(effective_preserve_hdrplus)
    )
    require_hdr = bool(require_dv or require_hdr10plus)
    normalized_target = normalize_video_codec(target_codec)
    if not require_hdr and normalized_target in {"hevc", "av1"}:
        require_hdr = source_has_hdr10_base(media_info)
    min_depth = 10 if normalized_target in {"hevc", "av1"} and require_hdr else None
    return require_hdr, require_dv, require_hdr10plus, min_depth


def build_media_contract(
    *,
    media_info,
    file_override: dict | None,
    container: str,
    pipeline: str,
    strip_only: bool,
    effective_codec: str,
    effective_preserve_hdrplus: bool,
    subtitle_rules: dict | None,
    effective_scale_mode: str | None,
    crop_filter: str | None,
    audio_planner: Callable[..., Any],
    subtitle_planner: Callable[..., Any],
    mp4_storage_planner: Callable[..., Any],
    audio_codec_family: Callable[[str | None], str],
    subtitle_codec_family: Callable[[str | None], str],
) -> ExpectedMediaContract:
    audio_tracks = _build_audio_tracks(
        media_info,
        file_override,
        container,
        audio_planner=audio_planner,
        audio_codec_family=audio_codec_family,
    )
    subtitle_tracks = _build_subtitle_tracks(
        media_info,
        file_override,
        container,
        strip_only,
        subtitle_rules,
        subtitle_planner=subtitle_planner,
        mp4_storage_planner=mp4_storage_planner,
        subtitle_codec_family=subtitle_codec_family,
    )
    primary = getattr(media_info, "primary_video", None)
    source_codec = normalize_video_codec(getattr(primary, "codec", ""))
    target_codec = source_codec if strip_only else normalize_video_codec(effective_codec)
    width, height = _expected_dimensions(media_info, strip_only, effective_scale_mode, crop_filter)
    require_hdr, require_dv, require_hdr10plus, min_depth = _video_requirements(
        media_info,
        pipeline=pipeline,
        strip_only=strip_only,
        target_codec=target_codec,
        effective_preserve_hdrplus=effective_preserve_hdrplus,
    )
    return ExpectedMediaContract(
        container=str(container or "").lower(),
        video_codec=target_codec,
        video_stream_count=1,
        audio_tracks=audio_tracks,
        subtitle_tracks=subtitle_tracks,
        min_video_bit_depth=min_depth,
        require_hdr=require_hdr,
        require_dolby_vision=require_dv,
        require_hdr10plus=require_hdr10plus,
        expected_width=width,
        expected_height=height,
    )
