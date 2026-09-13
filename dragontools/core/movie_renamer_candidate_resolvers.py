# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .german_title_variants import german_umlaut_search_variants
from .movie_renamer_episode_refresh import refresh_if_episode_title_fallback
from .movie_renamer_models import MovieSearchResolver, ParsedSeriesReleaseName, SeriesSearchResolver


def _resolve_raw_results(
    title: str,
    year: int | None,
    *,
    resolver: MovieSearchResolver | None,
    client: Any | None,
) -> Iterable[Any]:
    queries = german_umlaut_search_variants(title) or (title,)
    if resolver is not None:
        for query in queries:
            results = list(resolver(query, year) or [])
            if results:
                return results
        return ()
    if client is None or not hasattr(client, "search_movies"):
        return ()

    config = getattr(client, "config", None)
    fallback_language = getattr(config, "fallback_language", "")
    language = getattr(config, "language", "")
    for query in queries:
        results = client.search_movies(query, year=year)
        if results:
            return results
        if fallback_language and fallback_language != language:
            results = client.search_movies(query, year=year, language=fallback_language)
            if results:
                return results
    return ()


def _resolve_series_results(
    parsed: ParsedSeriesReleaseName,
    *,
    resolver: SeriesSearchResolver | None,
    client: Any | None,
) -> Iterable[Any]:
    queries = german_umlaut_search_variants(parsed.series) or (parsed.series,)
    if resolver is not None:
        for query in queries:
            results = list(resolver(query, parsed.season, parsed.episode, parsed.year) or [])
            if results:
                return results
        return ()
    if client is None:
        return ()

    if hasattr(client, "resolve_episode_candidates"):
        for query in queries:
            lookup = _series_lookup_path(parsed, query)
            suggestions = client.resolve_episode_candidates(lookup, limit=6)
            if suggestions:
                return refresh_if_episode_title_fallback(client, lookup, suggestions, parsed.episode)

    if hasattr(client, "resolve_episode_file"):
        for query in queries:
            suggestion = client.resolve_episode_file(_series_lookup_path(parsed, query))
            if suggestion is not None:
                return (suggestion,)

    if hasattr(client, "resolve_series"):
        for query in queries:
            series = client.resolve_series(query, year=parsed.year)
            if series is not None:
                return (series,)
    return ()


def _series_lookup_path(parsed: ParsedSeriesReleaseName, query: str) -> Path:
    lookup_name = str(query or parsed.series)
    if parsed.year:
        lookup_name += f" ({parsed.year})"
    lookup_name += f" - S{parsed.season:02d}E{parsed.episode:02d}{parsed.suffix or '.mkv'}"
    return Path(lookup_name)
