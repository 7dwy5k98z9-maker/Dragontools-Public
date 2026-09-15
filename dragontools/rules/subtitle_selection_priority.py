# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from ..core.lang_codes import language_matches, normalize_language_priority
from ..core.models import SubtitleStream
from .subtitle_rule_config import safe_int
from .subtitle_selection_common import dedupe_streams, sort_by_preferred_formats


def fallback_subtitle_streams(streams: list[SubtitleStream], preferred_formats: list[str], rules: dict[str, Any]) -> list[SubtitleStream]:
    policy = str(rules.get("fallback_if_no_priority_match", "keep_none")).strip().lower()
    ordered = sort_by_preferred_formats(streams, preferred_formats)
    if policy == "keep_all":
        return ordered
    if policy == "keep_first":
        return ordered[:1]
    return []


def select_subtitles_by_language_priority(streams: list[SubtitleStream], *, subtitle_rules: dict[str, Any], preferred_formats: list[str]) -> list[SubtitleStream]:
    priority = normalize_language_priority(subtitle_rules.get("language_priority"))
    if not priority:
        return fallback_subtitle_streams(streams, preferred_formats, subtitle_rules)
    max_languages = max(0, safe_int(subtitle_rules.get("max_languages", 1), 1))
    tracks_per_language = max(0, safe_int(subtitle_rules.get("tracks_per_language", 1), 1))
    chosen: list[SubtitleStream] = []
    matched_languages = 0
    for language in priority:
        matches = [stream for stream in streams if language_matches(stream.language, language)]
        if not matches:
            continue
        matched_languages += 1
        ordered = sort_by_preferred_formats(matches, preferred_formats)
        chosen.extend(ordered[: None if tracks_per_language == 0 else tracks_per_language])
        if max_languages > 0 and matched_languages >= max_languages:
            break
    return dedupe_streams(chosen) if chosen else fallback_subtitle_streams(streams, preferred_formats, subtitle_rules)


__all__ = ["fallback_subtitle_streams", "select_subtitles_by_language_priority"]
