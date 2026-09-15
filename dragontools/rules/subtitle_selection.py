# -*- coding: utf-8 -*-
"""Compatibility façade for subtitle selection helpers."""
from __future__ import annotations

from .subtitle_selection_common import (
    best_format_tie_group as _best_format_tie_group,
    build_custom_track_map as _build_custom_track_map,
    compatible_subtitles as _compatible_subtitles,
    dedupe_streams as _dedupe_streams,
    expand_preferred_formats as _expand_preferred_formats,
    fallback_languages as _fallback_languages,
    has_audio_language as _has_audio_language,
    has_german_audio as _has_german_audio,
    language_rank as _language_rank,
    match_by_language as _match_by_language,
    normalized_language_set as _normalized_language_set,
    preferred_formats as _preferred_formats,
    preferred_languages as _preferred_languages,
    sort_by_preferred_formats as _sort_by_preferred_formats,
)
from .subtitle_selection_priority import (
    fallback_subtitle_streams as _fallback_subtitle_streams,
    select_subtitles_by_language_priority as _select_subtitles_by_language_priority,
)
from .subtitle_selection_sidecar import (
    limit_external_sidecar_streams as _limit_external_sidecar_streams,
    sort_sidecar_candidates_by_rule as _sort_sidecar_candidates_by_rule,
)

__all__ = [name for name in globals() if name.startswith("_") and not name.startswith("__")]
