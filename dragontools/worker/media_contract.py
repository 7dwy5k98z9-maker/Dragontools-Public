# -*- coding: utf-8 -*-
"""Öffentliche Fassade für den erwarteten finalen Medienvertrag."""
from __future__ import annotations

from ..rules.audio_plan import compute_audio_track_plan
from ..rules.audio_rules import normalize_audio_codec
from ..rules.subtitle_rules import build_mp4_subtitle_storage_plan, compute_subtitle_plan
from .media_contract_builder import build_media_contract
from .media_contract_types import ExpectedAudioTrack, ExpectedMediaContract, ExpectedSubtitleTrack


def _audio_codec_family(codec: str | None) -> str:
    normalized = normalize_audio_codec(codec or "")
    if normalized.startswith("dts"):
        return "dts"
    if normalized.startswith("pcm"):
        return "pcm"
    return normalized


def _subtitle_codec_family(codec: str | None) -> str:
    value = str(codec or "").strip().lower()
    aliases = {
        "srt": "subrip",
        "text": "subrip",
        "subt": "mov_text",
        "tx3g": "mov_text",
        "vobsub": "dvd_subtitle",
    }
    return aliases.get(value, value)


def build_expected_media_contract(
    *,
    media_info,
    file_override: dict | None,
    container: str,
    pipeline: str,
    strip_only: bool,
    effective_codec: str,
    effective_preserve_hdrplus: bool,
    subtitle_rules: dict | None,
    effective_scale_mode: str | None = None,
    crop_filter: str | None = None,
) -> ExpectedMediaContract:
    return build_media_contract(
        media_info=media_info,
        file_override=file_override,
        container=container,
        pipeline=pipeline,
        strip_only=strip_only,
        effective_codec=effective_codec,
        effective_preserve_hdrplus=effective_preserve_hdrplus,
        subtitle_rules=subtitle_rules,
        effective_scale_mode=effective_scale_mode,
        crop_filter=crop_filter,
        audio_planner=compute_audio_track_plan,
        subtitle_planner=compute_subtitle_plan,
        mp4_storage_planner=build_mp4_subtitle_storage_plan,
        audio_codec_family=_audio_codec_family,
        subtitle_codec_family=_subtitle_codec_family,
    )


__all__ = [
    "ExpectedAudioTrack",
    "ExpectedSubtitleTrack",
    "ExpectedMediaContract",
    "build_expected_media_contract",
    "_audio_codec_family",
    "_subtitle_codec_family",
]
