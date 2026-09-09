# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from ..core.lang_codes import canonical_lang, language_matches, normalize_language_priority
from ..core.models import AudioStream, SubtitleStream
from ..core.type_utils import _safe_bool
from .subtitle_rule_config import (
    migrate_subtitle_rules,
    normalize_forced_plausibility as _normalize_forced_plausibility,
    safe_float as _safe_float,
    safe_int as _safe_int,
)
from .subtitle_selection import (
    _best_format_tie_group,
    _compatible_subtitles,
    _fallback_languages,
    _has_audio_language,
    _has_german_audio,
    _match_by_language,
    _preferred_formats,
    _preferred_languages,
    _sort_by_preferred_formats,
)

def _subtitle_event_rate_per_minute(
    stream: SubtitleStream,
    media_duration_s: float | None,
) -> float | None:
    event_count = _safe_int(getattr(stream, "event_count", None), 0)
    if event_count <= 0:
        return None
    duration_s = _safe_float(media_duration_s, 0.0)
    if duration_s <= 0:
        duration_s = _safe_float(getattr(stream, "duration_s", None), 0.0)
    if duration_s <= 0:
        return None
    return float(event_count) / max(duration_s / 60.0, 0.01)


def _evaluate_forced_burn_plausibility(
    stream: SubtitleStream | None,
    *,
    rules: dict[str, Any],
    media_duration_s: float | None,
) -> tuple[str, float | None, str | None]:
    if stream is None or not bool(getattr(stream, "forced", False)):
        return "ok", None, None

    burn_rules = rules.get("burn_in_rules", {}) if isinstance(rules.get("burn_in_rules"), dict) else {}
    config = _normalize_forced_plausibility(burn_rules.get("forced_plausibility"))
    if not _safe_bool(config.get("enabled"), True):
        return "ok", None, None

    rate = _subtitle_event_rate_per_minute(stream, media_duration_s)
    if rate is None:
        return "ok", None, None

    warn_limit = float(config.get("warn_events_per_minute", 3.0))
    block_limit = float(config.get("block_events_per_minute", 5.0))
    event_count = _safe_int(getattr(stream, "event_count", None), 0)

    if rate > block_limit:
        return (
            "block",
            rate,
            (
                "Forced-Untertitel wirkt wie Full Sub "
                f"({event_count} Events, {rate:.1f} Events/Min). "
                "Burn-In blockiert, Spur wird zusätzlich behalten/exportiert."
            ),
        )
    if rate > warn_limit:
        return (
            "warn",
            rate,
            (
                "Forced-Untertitel ist auffällig dicht "
                f"({event_count} Events, {rate:.1f} Events/Min). "
                "Burn-In bleibt aktiv, bitte Quelle prüfen."
            ),
        )
    return "ok", rate, None

def _resolve_auto_burn(
    streams: list[SubtitleStream],
    *,
    subtitle_rules: dict | None = None,
    audio_streams: list[AudioStream] | None = None,
    preferred_language: str = "de",
) -> tuple[SubtitleStream | None, list[SubtitleStream], str | None]:
    raw_rules = subtitle_rules or {}
    rules = migrate_subtitle_rules(raw_rules)
    burn_rules = rules.get("burn_in_rules", {}) if isinstance(rules.get("burn_in_rules"), dict) else {}

    auto_burn_forced = _safe_bool(burn_rules.get("auto_burn_forced", rules.get("auto_burn_forced", True)), True)
    ask_if_ambiguous = _safe_bool(burn_rules.get("ask_if_ambiguous", rules.get("ask_if_ambiguous", False)), False)
    never_burn_if_no_german_audio = bool(
        burn_rules.get("never_burn_if_no_german_audio", False)
    )
    never_burn_if_no_audio_language = bool(
        burn_rules.get("never_burn_if_no_audio_language", never_burn_if_no_german_audio)
    )
    burn_language = canonical_lang(burn_rules.get("burn_language") or preferred_language) or "de"

    if not auto_burn_forced:
        return None, [], "auto_burn_disabled"
    if never_burn_if_no_german_audio and rules.get("_legacy_language_rules") and not _has_german_audio(audio_streams):
        return None, [], "no_german_audio"
    if never_burn_if_no_audio_language and not rules.get("_legacy_language_rules") and not _has_audio_language(audio_streams, burn_language):
        return None, [], "no_audio_for_burn_language"

    preferred_langs = _preferred_languages(rules, preferred_language=preferred_language)
    fallback_langs = _fallback_languages(rules)
    preferred_formats = _preferred_formats(rules)

    forced = [
        stream for stream in _compatible_subtitles(streams)
        if bool(stream.forced)
    ]

    if rules.get("_legacy_language_rules"):
        candidates = _match_by_language(forced, preferred_langs)
        if not candidates:
            candidates = _match_by_language(forced, fallback_langs)
    else:
        burn_order = [burn_language]
        if str(burn_rules.get("burn_fallback", "none")).strip().lower() == "next_priority":
            for language in normalize_language_priority(rules.get("language_priority")):
                if language != burn_language:
                    burn_order.append(language)
        candidates = []
        for language in burn_order:
            candidates = [
                stream for stream in forced
                if language_matches(stream.language, language)
            ]
            if candidates:
                break

    candidates = _sort_by_preferred_formats(candidates, preferred_formats)

    if not candidates:
        return None, [], None
    if ask_if_ambiguous:
        best_tie_group = _best_format_tie_group(candidates, preferred_formats)
        if len(best_tie_group) > 1:
            return None, best_tie_group, "ambiguous"
    return candidates[0], candidates, None
