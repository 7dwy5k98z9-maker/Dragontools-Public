# -*- coding: utf-8 -*-
"""Focused subtitle-plan orchestration independent from public compatibility facade."""
from __future__ import annotations

from ..core.lang_codes import normalize_language_priority
from ..core.models import AudioStream, SubtitleOverride, SubtitleStream, normalize_override_dict
from ..core.type_utils import _safe_bool
from .subtitle_plan_models import SubtitlePlan
from .subtitle_rule_config import COMPATIBLE_SUBTITLE_CODECS, migrate_subtitle_rules
from .subtitle_selection import _build_custom_track_map, _dedupe_streams, _limit_external_sidecar_streams, _preferred_formats
from .subtitle_keep_policy import _build_auto_keep_streams, _sort_keep_candidates
from .subtitle_burn_policy import _evaluate_forced_burn_plausibility, _resolve_auto_burn


def compute_subtitle_plan_service(
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
    state = _initial_selection(
        subtitle_streams,
        audio_streams=audio_streams,
        subtitle_mode=subtitle_mode,
        custom_track_map=custom_track_map,
        legacy_override=legacy_override,
        subtitle_rules=subtitle_rules,
        media_duration_s=media_duration_s,
    )
    keep_streams = _finalize_keep_streams(state, subtitle_rules)
    external_streams, keep_streams = _apply_container_storage(
        keep_streams,
        subtitle_mode=subtitle_mode,
        burn_sub=state["burn_sub"],
        protected_forced_stream=state["protected_forced_stream"],
        subtitle_rules=subtitle_rules,
        container_copy_supported=container_copy_supported,
    )
    return SubtitlePlan(
        override_mode=subtitle_mode,
        burn_sub=state["burn_sub"],
        keep_streams=tuple(keep_streams),
        external_streams=tuple(external_streams),
        burn_candidates=tuple(state["burn_candidates"]),
        burn_blocked_reason=state["burn_blocked_reason"],
        burn_warnings=tuple(state["burn_warnings"]),
        burn_event_rate=state["burn_event_rate"],
    )


def _initial_selection(streams, *, audio_streams, subtitle_mode, custom_track_map, legacy_override, subtitle_rules, media_duration_s):
    state = {
        "burn_sub": None,
        "keep_streams": [],
        "burn_candidates": [],
        "burn_blocked_reason": None,
        "burn_warnings": [],
        "burn_event_rate": None,
        "protected_forced_stream": None,
    }
    if subtitle_mode == "custom" and custom_track_map:
        state["burn_sub"] = next((s for s in streams if custom_track_map.get(int(s.index), {}).get("burn_in")), None)
        state["keep_streams"] = [
            s for s in streams
            if custom_track_map.get(int(s.index), {}).get("keep")
            and (s.codec or "").lower() in COMPATIBLE_SUBTITLE_CODECS
        ]
        return state
    if subtitle_mode == "custom" and legacy_override.burn_mode in {"selected", "none"}:
        if legacy_override.burn_mode == "selected" and legacy_override.burn_stream_index is not None:
            state["burn_sub"] = next((s for s in streams if int(s.index) == int(legacy_override.burn_stream_index)), None)
        return state

    burn_sub, burn_candidates, blocked = _resolve_auto_burn(streams, subtitle_rules=subtitle_rules, audio_streams=audio_streams)
    state["burn_sub"], state["burn_candidates"], state["burn_blocked_reason"] = burn_sub, burn_candidates, blocked
    if burn_sub is not None:
        rules = migrate_subtitle_rules(subtitle_rules)
        plausibility, rate, message = _evaluate_forced_burn_plausibility(burn_sub, rules=rules, media_duration_s=media_duration_s)
        state["burn_event_rate"] = rate
        if plausibility == "block":
            state["protected_forced_stream"] = burn_sub
            state["burn_candidates"] = [burn_sub]
            state["burn_sub"] = None
            state["burn_blocked_reason"] = "forced_full_sub_suspected"
            if message:
                state["burn_warnings"].append(message)
        elif plausibility == "warn" and message:
            state["burn_warnings"].append(message)
    state["keep_streams"] = _build_auto_keep_streams(streams, subtitle_rules=subtitle_rules, burn_sub=state["burn_sub"])
    return state


def _finalize_keep_streams(state, subtitle_rules):
    keep_streams = list(state["keep_streams"])
    protected = state["protected_forced_stream"]
    burn_sub = state["burn_sub"]
    if protected is not None:
        keep_streams.append(protected)
    if burn_sub is not None:
        keep_streams = [s for s in keep_streams if int(s.index) != int(burn_sub.index)]
    keep_streams = _dedupe_streams(keep_streams)
    if protected is not None:
        rules = migrate_subtitle_rules(subtitle_rules)
        keep_streams = _sort_keep_candidates(
            keep_streams,
            _preferred_formats(rules),
            preferred_langs=set(), fallback_langs=set(),
            force_priority=_safe_bool(rules.get("force_priority"), True),
            language_priority=normalize_language_priority(rules.get("language_priority")),
        )
    return keep_streams


def _apply_container_storage(keep_streams, *, subtitle_mode, burn_sub, protected_forced_stream, subtitle_rules, container_copy_supported):
    external_streams = list(keep_streams)
    if container_copy_supported:
        return external_streams, keep_streams
    if subtitle_mode != "custom":
        if burn_sub is not None and bool(getattr(burn_sub, "forced", False)):
            external_streams = [s for s in external_streams if not bool(getattr(s, "forced", False))]
        if protected_forced_stream is not None:
            external_streams = [s for s in external_streams if int(s.index) != int(protected_forced_stream.index)]
        external_streams = _limit_external_sidecar_streams(external_streams, subtitle_rules=migrate_subtitle_rules(subtitle_rules))
        if protected_forced_stream is not None:
            external_streams.append(protected_forced_stream)
        external_streams = _dedupe_streams(external_streams)
    return external_streams, []
