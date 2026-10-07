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
    fields = _movie_candidate_fields(raw)
    if fields is None:
        return None
    title, year, tmdb_id, original_title, provider, provider_id = fields

    parsed_year = _int_or_none(year)
    score_titles = _movie_match_titles(raw, title, original_title)
    score = max(
        (_candidate_score(query_title, query_year, value, parsed_year) for value in score_titles),
        default=0.0,
    )
    return MovieRenameCandidate(
        title=title,
        year=parsed_year,
        tmdb_id=tmdb_id,
        original_title=original_title,
        provider=provider,
        provider_id=provider_id,
        score=score,
    )


def _movie_match_titles(raw: Any, localized_title: str, original_title: str) -> tuple[str, ...]:
    values: list[str] = [str(localized_title or "").strip(), str(original_title or "").strip()]
    if isinstance(raw, dict):
        aliases = raw.get("aliases")
        if isinstance(aliases, (list, tuple)):
            for alias in aliases:
                if isinstance(alias, str):
                    value = alias.strip()
                elif isinstance(alias, dict):
                    value = str(alias.get("name") or alias.get("title") or "").strip()
                else:
                    value = ""
                if value:
                    values.append(value)
    return tuple(dict.fromkeys(value for value in values if value))

def _series_candidate_from_result(
    raw: Any,
    parsed: ParsedSeriesReleaseName,
    *,
    title_exception: Callable[[str], str] = apply_title_exception,
) -> SeriesRenameCandidate | None:
    try:
        fields = _series_candidate_fields(raw, parsed)
    except (TypeError, ValueError, OverflowError):
        return None
    if fields is None:
        return None

    series, season, episode, title, year, provider, provider_id, episode_id, title_is_fallback = fields
    episode_verified = episode_id is not None and episode_id > 0
    match_names = _series_match_names(raw, series)
    scored = [(_series_score(parsed, name, season, episode, title, year), name) for name in match_names]
    score, best_match_name = max(scored, default=(0.0, series), key=lambda item: item[0])
    match_reason = "Originaltitel" if best_match_name != series and score > 0.0 else ""

    alias_title = title_exception(parsed.series).strip()
    if (season, episode) == (parsed.season, parsed.episode) and _compare_text(alias_title) != _compare_text(parsed.series):
        if max((_series_title_similarity(alias_title, name) for name in match_names), default=0.0) >= 0.98:
            score = 1.0
            match_reason = "Aliasregel"

    if title_is_fallback:
        score = min(score, 0.92 if episode_verified else 0.85)
        match_reason = "Episodentitel offen" if episode_verified else "Episode noch nicht in Metadaten"

    # Apply after alias rules: a matching title cannot prove the right remake.
    if parsed.year is not None and year != parsed.year:
        score = min(score, 0.89)
        if year is not None or match_reason != "Aliasregel":
            match_reason = "Jahr nicht bestätigt" if year is None else "Abweichendes Jahr"

    multi_episodes = parsed.episode_numbers if len(parsed.episode_numbers) > 1 else ()
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
        episodes=multi_episodes,
        episode_titles=((title,) if multi_episodes and title else ()),
        title_mode=("first" if multi_episodes else "all"),
    )


def _series_match_names(raw: Any, localized_name: str) -> tuple[str, ...]:
    """Return localized/original provider names used only for identity scoring."""
    values: list[str] = [str(localized_name or "").strip()]
    if isinstance(raw, dict):
        for key in (
            "original_show_name", "original_name", "originalName",
            "original_title", "originalTitle", "name", "series", "show_name",
        ):
            value = str(raw.get(key) or "").strip()
            if value:
                values.append(value)
    else:
        for attr in ("original_show_name", "original_name", "original_title", "name", "show_name"):
            value = str(getattr(raw, attr, "") or "").strip()
            if value:
                values.append(value)
    return tuple(dict.fromkeys(value for value in values if value))

def _series_candidate_fields(
    raw: Any,
    parsed: ParsedSeriesReleaseName,
) -> tuple[str, int, int, str, int | None, str, int | None, int | None, bool] | None:
    if raw is None:
        return None

    if hasattr(raw, "season_number") and hasattr(raw, "episode_number"):
        return _episode_object_fields(raw, parsed)

    if hasattr(raw, "name") and hasattr(raw, "first_air_year"):
        episode = parsed.episode
        return (str(getattr(raw, "name", "") or parsed.series).strip(), parsed.season, episode,
            default_episode_title(episode), _year_from_value(getattr(raw, "first_air_year", None)),
            str(getattr(raw, "provider", "") or "metadata"),
            _int_or_none(getattr(raw, "provider_id", None) or getattr(raw, "tmdb_id", None)), None, True)

    if isinstance(raw, dict):
        return _episode_dict_fields(raw, parsed)
    return None


def _provided_number(raw, names, fallback):
    from .movie_renamer_season_override import normalize_episode_number
    for name in names:
        value = raw.get(name) if isinstance(raw, dict) else getattr(raw, name, None)
        if value is not None:
            return normalize_episode_number(value, minimum=0 if 'season' in name else 1)
    return fallback


def _episode_object_fields(raw, parsed):
    series = str(getattr(raw, "show_name", "") or parsed.series).strip()
    season = _provided_number(raw, ('season_number',), parsed.season)
    episode = _provided_number(raw, ('episode_number',), parsed.episode)
    title, derived_fallback = normalize_episode_metadata_title(
        getattr(raw, "title", ""),
        episode,
        source_path=parsed.source_name,
    )
    title_is_fallback = bool(getattr(raw, "title_is_fallback", False)) or derived_fallback
    provider = str(getattr(raw, "provider", "") or "metadata")
    provider_id = _int_or_none(getattr(raw, "series_provider_id", None) or getattr(raw, "series_tmdb_id", None))
    episode_id = _int_or_none(getattr(raw, "episode_provider_id", None) or getattr(raw, "episode_tmdb_id", None))
    year = _year_from_value(getattr(raw, "first_air_year", None))
    return series, season, episode, title, year, provider, provider_id, episode_id, title_is_fallback


def _episode_dict_fields(raw, parsed):
    series = str(raw.get("series") or raw.get("show_name") or raw.get("name") or parsed.series).strip()
    season = _provided_number(raw, ('season', 'season_number'), parsed.season)
    episode = _provided_number(raw, ('episode', 'episode_number'), parsed.episode)
    raw_title = raw.get("episode_title") if "episode_title" in raw else raw.get("title")
    title, derived_fallback = normalize_episode_metadata_title(raw_title, episode, source_path=parsed.source_name)
    return (
        series,
        season,
        episode,
        title,
        _year_from_value(raw.get("year") or raw.get("first_air_year")),
        str(raw.get("provider") or "metadata"),
        _int_or_none(raw.get("provider_id") or raw.get("series_id") or raw.get("tmdb_id")),
        _int_or_none(raw.get("episode_id") or raw.get("episode_provider_id") or raw.get("episode_tmdb_id")),
        bool(raw.get("title_is_fallback", False)) or derived_fallback,
    )


def _movie_candidate_fields(raw):
    if hasattr(raw, 'title'):
        return _movie_object_fields(raw)
    if isinstance(raw, dict):
        return _movie_dict_fields(raw)
    return None


def _movie_object_fields(raw):
    title = str(getattr(raw, "title") or getattr(raw, "original_title", "") or "").strip()
    year = getattr(raw, "release_year", None) or getattr(raw, "year", None)
    tmdb_id = getattr(raw, "tmdb_id", None)
    original_title = str(getattr(raw, "original_title", "") or "").strip()
    provider = str(getattr(raw, "provider", "") or "tmdb")
    provider_id = _int_or_none(getattr(raw, "provider_id", None) or tmdb_id)
    return title, year, tmdb_id, original_title, provider, provider_id


def _movie_dict_fields(raw):
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
    original_title = str(
        raw.get("original_title") or raw.get("originalTitle")
        or raw.get("original_name") or raw.get("originalName")
        or raw.get("name") or ""
    ).strip()
    provider = str(raw.get("provider") or "tmdb")
    provider_id = _int_or_none(raw.get("provider_id") or raw.get("id") or raw.get("tmdb_id"))
    return title, year, tmdb_id, original_title, provider, provider_id
