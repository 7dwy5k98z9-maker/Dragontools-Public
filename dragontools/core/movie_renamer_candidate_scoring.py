# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from .german_title_variants import fold_german_umlauts
from .movie_renamer_models import ParsedSeriesReleaseName
from .movie_renamer_parsing import _YEAR_RE


def _series_title_similarity(source_title: str, candidate_title: str) -> float:
    source_norm = _compare_text(source_title)
    candidate_norm = _compare_text(candidate_title)
    if not source_norm or not candidate_norm:
        return 0.0
    ratio = SequenceMatcher(None, source_norm, candidate_norm).ratio()
    ratio = max(
        ratio,
        SequenceMatcher(
            None,
            _drop_leading_article(source_norm),
            _drop_leading_article(candidate_norm),
        ).ratio(),
    )
    return max(0.0, min(1.0, ratio))


def _series_score(
    parsed: ParsedSeriesReleaseName,
    series: str,
    season: int,
    episode: int,
    title: str,
    candidate_year: int | None = None,
) -> float:
    # Compatibility: title/year are accepted because external/custom resolvers
    # historically call this score contract. Confidence intentionally reflects
    # series-title similarity; season/episode mismatches only subtract trust.
    del title, candidate_year
    ratio = _series_title_similarity(parsed.series, series)
    if int(season) != int(parsed.season):
        ratio -= 0.25
    if int(episode) != int(parsed.episode):
        ratio -= 0.25
    return max(0.0, min(1.0, ratio))


def _candidate_score(
    query_title: str,
    query_year: int | None,
    result_title: str,
    result_year: int | None,
) -> float:
    query_norm = _compare_text(query_title)
    result_norm = _compare_text(result_title)
    ratio = SequenceMatcher(None, query_norm, result_norm).ratio()
    ratio = max(
        ratio,
        SequenceMatcher(
            None,
            _drop_leading_article(query_norm),
            _drop_leading_article(result_norm),
        ).ratio(),
    )
    if query_year and result_year:
        if int(query_year) == int(result_year):
            ratio += 0.25
        else:
            ratio -= min(0.25, abs(int(query_year) - int(result_year)) * 0.04)
    elif query_year or result_year:
        ratio -= 0.03
    return max(0.0, min(1.0, round(ratio, 3)))


def _compare_text(value: str) -> str:
    text = fold_german_umlauts(value)
    text = text.replace("&", " und ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _drop_leading_article(value: str) -> str:
    return re.sub(r"^(?:der|die|das|the|a|an|le|la|les|el|il)\s+", "", value, flags=re.IGNORECASE).strip()


def _year_from_value(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value if 1800 <= value <= 2200 else None
    match = _YEAR_RE.search(str(value))
    return int(match.group(1)) if match else None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
