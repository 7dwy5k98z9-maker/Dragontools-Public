# -*- coding: utf-8 -*-
"""Compatibility facade and orchestration for subtitle policy decisions.

Selection, forced-burn plausibility, and MP4 storage policy live in focused
modules. Public imports remain stable for workers, GUI code, and rule previews.
"""
from __future__ import annotations

from ..core.models import AudioStream, SubtitleOverride, SubtitleStream
from .subtitle_plan_models import MP4SubtitleStoragePlan, SubtitlePlan
from .subtitle_rule_config import (
    COMPATIBLE_SUBTITLE_CODECS,
    DEFAULT_PREFERRED_SUBTITLE_FORMATS,
    ENGLISH_LANGUAGE_CODES,
    GERMAN_LANGUAGE_CODES,
    IMAGE_SUBTITLE_CODECS,
    TEXT_SUBTITLE_CODECS,
    migrate_subtitle_rules,
)
from .subtitle_keep_policy import _build_auto_keep_streams
from .subtitle_burn_policy import _resolve_auto_burn
from .subtitle_plan_service import compute_subtitle_plan_service
from .subtitle_storage import (
    additional_sidecars_enabled,
    any_sidecar_export_enabled,
    ass_to_srt_sidecar_enabled,
    build_mp4_subtitle_storage_plan,
    mp4_sidecars_enabled,
    text_to_srt_sidecar_enabled,
)

def compute_subtitle_plan(
    subtitle_streams: list[SubtitleStream],
    *,
    audio_streams: list[AudioStream] | None = None,
    file_override: dict | None = None,
    subtitle_rules: dict | None = None,
    container_copy_supported: bool = True,
    media_duration_s: float | None = None,
) -> SubtitlePlan:
    return compute_subtitle_plan_service(
        subtitle_streams,
        audio_streams=audio_streams,
        file_override=file_override,
        subtitle_rules=subtitle_rules,
        container_copy_supported=container_copy_supported,
        media_duration_s=media_duration_s,
    )

def choose_burn_subtitle(
    streams: list[SubtitleStream],
    preferred_language: str = "de",
    override: SubtitleOverride | None = None,
    subtitle_rules: dict | None = None,
    audio_streams: list[AudioStream] | None = None,
) -> SubtitleStream | None:
    if override and override.burn_mode == "none":
        return None
    if override and override.burn_mode == "selected" and override.burn_stream_index is not None:
        for stream in streams:
            if stream.index == override.burn_stream_index:
                return stream
        return None

    burn_sub, _, _ = _resolve_auto_burn(
        streams,
        subtitle_rules=subtitle_rules,
        audio_streams=audio_streams,
        preferred_language=preferred_language,
    )
    return burn_sub


def choose_keep_subtitles(
    streams: list[SubtitleStream],
    *,
    subtitle_rules: dict | None = None,
) -> list[SubtitleStream]:
    return _build_auto_keep_streams(
        streams,
        subtitle_rules=subtitle_rules,
    )


__all__ = [
    "COMPATIBLE_SUBTITLE_CODECS",
    "DEFAULT_PREFERRED_SUBTITLE_FORMATS",
    "ENGLISH_LANGUAGE_CODES",
    "GERMAN_LANGUAGE_CODES",
    "IMAGE_SUBTITLE_CODECS",
    "MP4SubtitleStoragePlan",
    "SubtitlePlan",
    "TEXT_SUBTITLE_CODECS",
    "additional_sidecars_enabled",
    "any_sidecar_export_enabled",
    "ass_to_srt_sidecar_enabled",
    "build_mp4_subtitle_storage_plan",
    "choose_burn_subtitle",
    "choose_keep_subtitles",
    "compute_subtitle_plan",
    "migrate_subtitle_rules",
    "mp4_sidecars_enabled",
    "text_to_srt_sidecar_enabled",
]
