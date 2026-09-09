# -*- coding: utf-8 -*-
"""Compatibility facade and orchestration for subtitle policy decisions.

Selection, forced-burn plausibility, and MP4 storage policy live in focused
modules. Public imports remain stable for workers, GUI code, and rule previews.
"""
from __future__ import annotations

from ..core.lang_codes import normalize_language_priority
from ..core.models import AudioStream, SubtitleOverride, SubtitleStream, normalize_override_dict
from ..core.type_utils import _safe_bool
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
from .subtitle_selection import (
    _build_custom_track_map,
    _dedupe_streams,
    _limit_external_sidecar_streams,
    _preferred_formats,
)
from .subtitle_keep_policy import _build_auto_keep_streams, _sort_keep_candidates
from .subtitle_burn_policy import _evaluate_forced_burn_plausibility, _resolve_auto_burn
from .subtitle_storage import build_mp4_subtitle_storage_plan, mp4_sidecars_enabled

def compute_subtitle_plan(
    subtitle_streams: list[SubtitleStream],
    *,
    audio_streams: list[AudioStream] | None = None,
    file_override: dict | None = None,
    subtitle_rules: dict | None = None,
    container_copy_supported: bool = True,
    media_duration_s: float | None = None,
) -> SubtitlePlan:
    ov = normalize_override_dict(file_override)
    subtitle_mode = ov.get("subtitle_mode", "auto")
    custom_track_map = _build_custom_track_map(ov) if subtitle_mode == "custom" else {}
    legacy = ov.get("_legacy") or {}
    legacy_override = SubtitleOverride(
        burn_mode=legacy.get("burn_mode", "auto"),
        burn_stream_index=legacy.get("burn_stream_index"),
    )

    burn_sub: SubtitleStream | None = None
    keep_streams: list[SubtitleStream] = []
    burn_candidates: list[SubtitleStream] = []
    burn_blocked_reason: str | None = None
    burn_warnings: list[str] = []
    burn_event_rate: float | None = None
    protected_forced_stream: SubtitleStream | None = None

    if subtitle_mode == "custom" and custom_track_map:
        burn_sub = next(
            (
                stream for stream in subtitle_streams
                if custom_track_map.get(int(stream.index), {}).get("burn_in")
            ),
            None,
        )
        keep_streams = [
            stream for stream in subtitle_streams
            if custom_track_map.get(int(stream.index), {}).get("keep")
            and (stream.codec or "").lower() in COMPATIBLE_SUBTITLE_CODECS
        ]
    elif subtitle_mode == "custom" and legacy_override.burn_mode in {"selected", "none"}:
        if legacy_override.burn_mode == "selected" and legacy_override.burn_stream_index is not None:
            burn_sub = next(
                (
                    stream for stream in subtitle_streams
                    if int(stream.index) == int(legacy_override.burn_stream_index)
                ),
                None,
            )
        keep_streams = []
    else:
        burn_sub, burn_candidates, burn_blocked_reason = _resolve_auto_burn(
            subtitle_streams,
            subtitle_rules=subtitle_rules,
            audio_streams=audio_streams,
        )
        if burn_sub is not None:
            rules = migrate_subtitle_rules(subtitle_rules)
            plausibility, rate, message = _evaluate_forced_burn_plausibility(
                burn_sub,
                rules=rules,
                media_duration_s=media_duration_s,
            )
            burn_event_rate = rate
            if plausibility == "block":
                protected_forced_stream = burn_sub
                burn_candidates = [burn_sub]
                burn_sub = None
                burn_blocked_reason = "forced_full_sub_suspected"
                if message:
                    burn_warnings.append(message)
            elif plausibility == "warn" and message:
                burn_warnings.append(message)
        keep_streams = _build_auto_keep_streams(
            subtitle_streams,
            subtitle_rules=subtitle_rules,
            burn_sub=burn_sub,
        )

    if protected_forced_stream is not None:
        keep_streams.append(protected_forced_stream)

    if burn_sub is not None:
        keep_streams = [
            stream for stream in keep_streams
            if int(stream.index) != int(burn_sub.index)
        ]

    keep_streams = _dedupe_streams(keep_streams)
    if protected_forced_stream is not None:
        sorted_rules = migrate_subtitle_rules(subtitle_rules)
        keep_streams = _sort_keep_candidates(
            keep_streams,
            _preferred_formats(sorted_rules),
            preferred_langs=set(),
            fallback_langs=set(),
            force_priority=_safe_bool(sorted_rules.get("force_priority"), True),
            language_priority=normalize_language_priority(sorted_rules.get("language_priority")),
        )
    external_streams = list(keep_streams)
    if not container_copy_supported:
        if subtitle_mode != "custom":
            if burn_sub is not None and bool(getattr(burn_sub, "forced", False)):
                external_streams = [
                    stream for stream in external_streams
                    if not bool(getattr(stream, "forced", False))
                ]
            if protected_forced_stream is not None:
                external_streams = [
                    stream for stream in external_streams
                    if int(stream.index) != int(protected_forced_stream.index)
                ]
            external_streams = _limit_external_sidecar_streams(
                external_streams,
                subtitle_rules=migrate_subtitle_rules(subtitle_rules),
            )
            if protected_forced_stream is not None:
                external_streams.append(protected_forced_stream)
            external_streams = _dedupe_streams(external_streams)
        keep_streams = []

    return SubtitlePlan(
        override_mode=subtitle_mode,
        burn_sub=burn_sub,
        keep_streams=tuple(keep_streams),
        external_streams=tuple(external_streams),
        burn_candidates=tuple(burn_candidates),
        burn_blocked_reason=burn_blocked_reason,
        burn_warnings=tuple(burn_warnings),
        burn_event_rate=burn_event_rate,
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
    "build_mp4_subtitle_storage_plan",
    "choose_burn_subtitle",
    "choose_keep_subtitles",
    "compute_subtitle_plan",
    "migrate_subtitle_rules",
    "mp4_sidecars_enabled",
]
