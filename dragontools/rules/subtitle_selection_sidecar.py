# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from ..core.lang_codes import language_matches, normalize_language_priority
from ..core.models import SubtitleStream
from ..core.type_utils import _safe_bool
from .subtitle_rule_config import safe_int
from .subtitle_selection_common import dedupe_streams, preferred_formats


def sort_sidecar_candidates_by_rule(streams: list[SubtitleStream], formats: list[str], *, force_priority: bool) -> list[SubtitleStream]:
    order = {fmt.strip().lower(): i for i, fmt in enumerate(formats)}
    return sorted(
        dedupe_streams(streams),
        key=lambda stream: (order.get((stream.codec or "").lower(), len(formats)), 0 if (force_priority and bool(stream.forced)) else 1, int(stream.index)),
    )


def _fallback(streams: list[SubtitleStream], *, formats: list[str], force_priority: bool, policy: str) -> list[SubtitleStream]:
    ordered = sort_sidecar_candidates_by_rule(streams, formats, force_priority=force_priority)
    if policy == "keep_all":
        return ordered
    if policy == "keep_first":
        return ordered[:1]
    return []


def limit_external_sidecar_streams(streams: list[SubtitleStream], *, subtitle_rules: dict[str, Any]) -> list[SubtitleStream]:
    streams = dedupe_streams(streams)
    if not streams:
        return []
    formats = preferred_formats(subtitle_rules)
    force_priority = _safe_bool(subtitle_rules.get("force_priority"), True)
    max_languages = max(0, safe_int(subtitle_rules.get("max_languages", 1), 1))
    tracks_per_language = max(0, safe_int(subtitle_rules.get("tracks_per_language", 1), 1))
    if max_languages == 0 and tracks_per_language == 0:
        return sort_sidecar_candidates_by_rule(streams, formats, force_priority=force_priority)
    priority = normalize_language_priority(subtitle_rules.get("language_priority"))
    policy = str(subtitle_rules.get("fallback_if_no_priority_match", "keep_none")).strip().lower()
    if not priority:
        return _fallback(streams, formats=formats, force_priority=force_priority, policy=policy)
    chosen: list[SubtitleStream] = []
    matched_languages = 0
    for language in priority:
        matches = [stream for stream in streams if language_matches(stream.language, language)]
        if not matches:
            continue
        matched_languages += 1
        ordered = sort_sidecar_candidates_by_rule(matches, formats, force_priority=force_priority)
        chosen.extend(ordered[: None if tracks_per_language == 0 else tracks_per_language])
        if max_languages > 0 and matched_languages >= max_languages:
            break
    return dedupe_streams(chosen) if chosen else _fallback(streams, formats=formats, force_priority=force_priority, policy=policy)


__all__ = ["sort_sidecar_candidates_by_rule", "limit_external_sidecar_streams"]
