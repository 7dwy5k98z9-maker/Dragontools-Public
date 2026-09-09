# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from ..core.lang_codes import normalize_language_priority
from ..core.models import SubtitleStream
from ..core.type_utils import _safe_bool
from .subtitle_rule_config import ENGLISH_LANGUAGE_CODES, GERMAN_LANGUAGE_CODES, migrate_subtitle_rules, safe_int as _safe_int
from .subtitle_selection import (
    _compatible_subtitles,
    _dedupe_streams,
    _fallback_languages,
    _language_rank,
    _match_by_language,
    _preferred_formats,
    _preferred_languages,
    _select_subtitles_by_language_priority,
)

def _sort_keep_candidates(
    streams: list[SubtitleStream],
    preferred_formats: list[str],
    *,
    preferred_langs: set[str],
    fallback_langs: set[str],
    force_priority: bool,
    language_priority: list[str] | None = None,
) -> list[SubtitleStream]:
    format_order = {fmt.strip().lower(): i for i, fmt in enumerate(preferred_formats)}

    def legacy_language_rank(stream: SubtitleStream) -> int:
        lang = (stream.language or "").strip().lower()
        if lang in preferred_langs:
            return 0
        if lang in fallback_langs:
            return 1
        if lang in ENGLISH_LANGUAGE_CODES:
            return 2
        if lang in GERMAN_LANGUAGE_CODES:
            return 3
        return 4

    return sorted(
        _dedupe_streams(streams),
        key=lambda stream: (
            0 if (force_priority and bool(stream.forced)) else 1,
            _language_rank(stream, language_priority) if language_priority else legacy_language_rank(stream),
            format_order.get((stream.codec or "").lower(), len(preferred_formats)),
            int(stream.index),
        ),
    )

def _build_priority_keep_streams(
    compatible: list[SubtitleStream],
    *,
    subtitle_rules: dict[str, Any],
    burn_sub: SubtitleStream | None = None,
) -> list[SubtitleStream]:
    keep_rules = subtitle_rules.get("keep_rules", {}) if isinstance(subtitle_rules.get("keep_rules"), dict) else {}
    preferred_formats = _preferred_formats(subtitle_rules)
    force_priority = _safe_bool(subtitle_rules.get("force_priority"), True)
    priority = normalize_language_priority(subtitle_rules.get("language_priority"))
    burned_forced = burn_sub is not None and bool(getattr(burn_sub, "forced", False))

    chosen: list[SubtitleStream] = []

    if keep_rules.get("keep_forced", True):
        chosen.extend([stream for stream in compatible if bool(stream.forced)])

    may_keep_selected = _safe_bool(keep_rules.get("keep_selected_languages"), True)
    if keep_rules.get("keep_if_no_burn_only", False) and burned_forced:
        may_keep_selected = False

    if may_keep_selected and keep_rules.get("keep_regular", True):
        regular_candidates = [stream for stream in compatible if not bool(stream.forced)]
        chosen.extend(_select_subtitles_by_language_priority(
            regular_candidates,
            subtitle_rules=subtitle_rules,
            preferred_formats=preferred_formats,
        ))

    return _sort_keep_candidates(
        chosen,
        preferred_formats,
        preferred_langs=set(),
        fallback_langs=set(),
        force_priority=force_priority,
        language_priority=priority,
    )


def _build_auto_keep_streams(
    streams: list[SubtitleStream],
    *,
    subtitle_rules: dict | None = None,
    burn_sub: SubtitleStream | None = None,
) -> list[SubtitleStream]:
    rules = migrate_subtitle_rules(subtitle_rules)
    keep_rules = rules.get("keep_rules", {}) if isinstance(rules.get("keep_rules"), dict) else {}
    preferred_langs = _preferred_languages(rules)
    fallback_langs = _fallback_languages(rules)
    preferred_formats = _preferred_formats(rules)
    force_priority = _safe_bool(rules.get("force_priority"), True)
    compatible = _compatible_subtitles(streams)

    if not compatible:
        return []

    if not rules.get("_legacy_language_rules"):
        return _build_priority_keep_streams(
            compatible,
            subtitle_rules=rules,
            burn_sub=burn_sub,
        )

    chosen: list[SubtitleStream] = []

    if keep_rules.get("keep_forced", True):
        chosen.extend([stream for stream in compatible if bool(stream.forced)])

    keep_all_german = _safe_bool(keep_rules.get("keep_all_german"), True)
    keep_german_if_no_burn = _safe_bool(keep_rules.get("keep_german_if_no_burn"), False)
    burned_forced = burn_sub is not None and bool(getattr(burn_sub, "forced", False))

    tracks_per_language = max(0, _safe_int(rules.get("tracks_per_language", 1), 1))

    def legacy_limited(matches: list[SubtitleStream]) -> list[SubtitleStream]:
        ordered = _sort_keep_candidates(
            matches,
            preferred_formats,
            preferred_langs=preferred_langs,
            fallback_langs=fallback_langs,
            force_priority=force_priority,
        )
        if tracks_per_language == 0:
            return ordered
        return ordered[:tracks_per_language]

    if keep_all_german or (keep_german_if_no_burn and not burned_forced):
        regular_matches = [
            stream for stream in _match_by_language(compatible, preferred_langs)
            if not bool(stream.forced)
        ]
        chosen.extend(legacy_limited(regular_matches))

    # Wichtig: bevorzugte Sprachen duerfen NICHT automatisch wieder alle deutschen
    # Untertitel erzwingen. Sonst wirkt keep_all_german=False nicht.
    if keep_rules.get("keep_english_fallback", False):
        has_preferred_or_forced = bool(chosen)
        if not has_preferred_or_forced:
            fallback_matches = [
                stream for stream in _match_by_language(compatible, fallback_langs)
                if not bool(stream.forced)
            ]
            if fallback_matches:
                chosen.extend(legacy_limited(fallback_matches))
            else:
                english_matches = [
                    stream for stream in _match_by_language(compatible, ENGLISH_LANGUAGE_CODES)
                    if not bool(stream.forced)
                ]
                chosen.extend(legacy_limited(english_matches))

    return _sort_keep_candidates(
        chosen,
        preferred_formats,
        preferred_langs=preferred_langs,
        fallback_langs=fallback_langs,
        force_priority=force_priority,
    )
