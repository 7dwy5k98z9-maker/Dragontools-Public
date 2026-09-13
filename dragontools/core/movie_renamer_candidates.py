# -*- coding: utf-8 -*-
"""Compatibility facade for rename-candidate resolution, mapping and ranking."""
from __future__ import annotations

from .movie_renamer_candidate_mapping import _candidate_from_result, _series_candidate_from_result
from .movie_renamer_candidate_order import _limit_candidates_with_provider_coverage, _sort_candidates
from .movie_renamer_candidate_resolvers import _resolve_raw_results, _resolve_series_results, _series_lookup_path
from .movie_renamer_candidate_scoring import (
    _candidate_score,
    _compare_text,
    _drop_leading_article,
    _int_or_none,
    _series_score,
    _series_title_similarity,
    _year_from_value,
)

__all__ = [
    "_resolve_raw_results",
    "_resolve_series_results",
    "_series_lookup_path",
    "_candidate_from_result",
    "_series_candidate_from_result",
    "_series_title_similarity",
    "_series_score",
    "_sort_candidates",
    "_limit_candidates_with_provider_coverage",
    "_candidate_score",
    "_compare_text",
    "_drop_leading_article",
    "_year_from_value",
    "_int_or_none",
]
