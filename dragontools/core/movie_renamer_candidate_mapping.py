# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Callable

from .movie_renamer_candidate_scoring import (
    _candidate_score,
    _compare_text,
    _int_or_none,
    _series_score,
    _series_title_similarity,
    _year_from_value,
)
from .movie_renamer_models import MovieRenameCandidate, ParsedSeriesReleaseName, SeriesRenameCandidate
from .online_metadata_common import default_episode_title, normalize_episode_metadata_title
from ..rules.renamer_rules import apply_title_exception


def _candidate_from_result(
    raw: Any,
    query_title: str,
    query_year: int | None,
) -> MovieRenameCandidate | None:
    if raw is None:
        return None
    if hasattr(raw, "title"):
        title = str(getattr(raw, "title") or getattr(raw, "original_title", "") or "").strip()
        year = getattr(raw, "release_year", None) or getattr(raw, "year", None)
        tmdb_id = getattr(raw, "tmdb_id", None)
        original_title = str(getattr(raw, "original_title", "") or "").strip()
        provider = str(getattr(raw, "provider", "") or "tmdb")
        provider_id = _int_or_none(getattr(raw, "provider_id", None) or tmdb_id)
    elif isinstance(raw, dict):
        title = str(
            raw.get("title")
            or raw.get("name_translated")
            or raw.get("name")
            or raw.get("original_title")
            or ""
        ).strip()
        year = _year_from_value(
            raw.get("release_date")
            or raw.get("releaseDate")
            or raw.get("first_release")
            or raw.get("firstRelease")
            or raw.get("first_air_date")
            or raw.get("year")
        )
        tmdb_id = _int_or_none(raw.get("id") or raw.get("tmdb_id") or raw.get("tvdb_id"))
        original_title = str(raw.get("original_title") or raw.get("original_name") or raw.get("name") or "").strip()
        provider = str(raw.get("provider") or "tmdb")
        provider_id = _int_or_none(raw.get("provider_id") or raw.get("id") or raw.get("tmdb_id"))
    else:
        return None

    parsed_year = _int_or_none(year)
    return MovieRenameCandidate(
        title=title,
        year=parsed_year,
        tmdb_id=tmdb_id,
        original_title=original_title,
        provider=provider,
        provider_id=provider_id,
        score=_candidate_score(query_title, query_year, title, parsed_year),
    )


def _series_candidate_from_result(
    raw: Any,
    parsed: ParsedSeriesReleaseName,
    *,
    title_exception: Callable[[str], str] = apply_title_exception,
) -> SeriesRenameCandidate | None:
    fields = _series_candidate_fields(raw, parsed)
    if fields is None:
        return None

    series, season, episode, title, year, provider, provider_id, episode_id, title_is_fallback = fields
    episode_verified = episode_id is not None and episode_id > 0
    score = _series_score(parsed, series, season, episode, title, year)
    match_reason = ""

    alias_title = title_exception(parsed.series).strip()
    if _compare_text(alias_title) != _compare_text(parsed.series):
        if _series_title_similarity(alias_title, series) >= 0.98:
            score = 1.0
            match_reason = "Aliasregel"

    if title_is_fallback:
        score = min(score, 0.92 if episode_verified else 0.85)
        match_reason = "Episodentitel offen" if episode_verified else "Episode noch nicht in Metadaten"

    return SeriesRenameCandidate(
        series=series or parsed.series,
        season=season,
        episode=episode,
        episode_title=title,
        year=year,
        provider=provider,
        provider_id=provider_id,
        episode_id=episode_id,
        score=max(0.0, min(1.0, round(score, 3))),
        match_reason=match_reason,
    )


def _series_candidate_fields(
    raw: Any,
    parsed: ParsedSeriesReleaseName,
) -> tuple[str, int, int, str, int | None, str, int | None, int | None, bool] | None:
    if raw is None:
        return None

    if hasattr(raw, "season_number") and hasattr(raw, "episode_number"):
        series = str(getattr(raw, "show_name", "") or parsed.series).strip()
        season = _int_or_none(getattr(raw, "season_number", None)) or parsed.season
        episode = _int_or_none(getattr(raw, "episode_number", None)) or parsed.episode
        title, derived_fallback = normalize_episode_metadata_title(
            getattr(raw, "title", ""),
            episode,
            source_path=parsed.source_name,
        )
        title_is_fallback = bool(getattr(raw, "title_is_fallback", False)) or derived_fallback
        provider = str(getattr(raw, "provider", "") or "metadata")
        provider_id = _int_or_none(getattr(raw, "series_provider_id", None) or getattr(raw, "series_tmdb_id", None))
        episode_id = _int_or_none(getattr(raw, "episode_provider_id", None) or getattr(raw, "episode_tmdb_id", None))
        year = _int_or_none(getattr(raw, "first_air_year", None)) or parsed.year
        return series, season, episode, title, year, provider, provider_id, episode_id, title_is_fallback

    if hasattr(raw, "name") and hasattr(raw, "first_air_year"):
        series = str(getattr(raw, "name", "") or parsed.series).strip()
        episode = parsed.episode
        return (
            series,
            parsed.season,
            episode,
            default_episode_title(episode),
            _int_or_none(getattr(raw, "first_air_year", None)) or parsed.year,
            str(getattr(raw, "provider", "") or "metadata"),
            _int_or_none(getattr(raw, "provider_id", None) or getattr(raw, "tmdb_id", None)),
            None,
            True,
        )

    if isinstance(raw, dict):
        series = str(raw.get("series") or raw.get("show_name") or raw.get("name") or parsed.series).strip()
        season = _int_or_none(raw.get("season") or raw.get("season_number")) or parsed.season
        episode = _int_or_none(raw.get("episode") or raw.get("episode_number")) or parsed.episode
        raw_title = raw.get("episode_title") if "episode_title" in raw else raw.get("title")
        title, derived_fallback = normalize_episode_metadata_title(raw_title, episode, source_path=parsed.source_name)
        return (
            series,
            season,
            episode,
            title,
            _int_or_none(raw.get("year") or raw.get("first_air_year")) or parsed.year,
            str(raw.get("provider") or "metadata"),
            _int_or_none(raw.get("provider_id") or raw.get("series_id") or raw.get("tmdb_id")),
            _int_or_none(raw.get("episode_id") or raw.get("episode_provider_id") or raw.get("episode_tmdb_id")),
            bool(raw.get("title_is_fallback", False)) or derived_fallback,
        )
    return None
