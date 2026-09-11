# -*- coding: utf-8 -*-
from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .online_metadata_common import (
    EpisodeMetadataSuggestion,
    OnlineMetadataError,
    _float_or_none,
    _int_or_none,
    compare_metadata_text,
    normalize_episode_metadata_title,
    parse_series_query,
)
from .online_metadata_tvdb_helpers import (
    _tvdb_localized_title,
    _tvdb_text,
    _year_from_tvdb_record,
)


def _candidate_request(path: str | Path):
    try:
        from ..rules.move_rules import parse_series_match_details
        from ..rules.renamer_rules import (
            candidate_discovery_floor,
            retry_without_year_enabled,
            series_search_queries,
        )
    except Exception:
        return None

    parsed = parse_series_match_details(Path(path).name)
    if not parsed or not parsed.get("series"):
        return None
    series_query = parse_series_query(Path(path).name)
    query = (series_query.title or str(parsed["series"])).strip()
    season = int(parsed.get("season") or 0)
    episode = int(parsed.get("episode") or 0)
    if not query or season < 0 or episode <= 0:
        return None
    return {
        "query": query,
        "year": series_query.year,
        "season": season,
        "episode": episode,
        "search_terms": series_search_queries(query),
        "retry_without_year": retry_without_year_enabled(),
        "title_floor": candidate_discovery_floor(),
    }


def _search_languages(client) -> tuple[str, ...]:
    primary = client.config.language
    fallback = client.config.fallback_language
    return (primary,) if fallback == primary else (primary, fallback)


def _collect_records(client, request: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen_ids: set[int] = set()

    def collect(term: str, year: int | None) -> None:
        found: list[dict[str, Any]] = []
        for language in _search_languages(client):
            try:
                found = client.search_series(term, year=year, language=language)
            except OnlineMetadataError:
                found = []
            if found:
                break
        for record in found or []:
            record_id = _int_or_none(record.get("tvdb_id") or record.get("id") or record.get("seriesId"))
            if record_id is None or record_id in seen_ids:
                continue
            seen_ids.add(record_id)
            records.append(record)

    search_terms = list(request["search_terms"])
    for term in search_terms[:2]:
        collect(term, request["year"])
        if request["year"] is not None and request["retry_without_year"]:
            collect(term, None)
    for term in search_terms[2:]:
        collect(term, None)
    return records


def _record_rank(client, record: dict[str, Any], *, query: str, year: int | None) -> tuple[float, int, float]:
    title = (
        _tvdb_localized_title(record, client.config.language)
        or _tvdb_localized_title(record, client.config.fallback_language)
        or _tvdb_text(record, "name_translated", "name")
    )
    title_score = SequenceMatcher(
        None,
        compare_metadata_text(query),
        compare_metadata_text(title),
    ).ratio()
    candidate_year = _year_from_tvdb_record(record)
    year_score = int(year is not None and candidate_year is not None and int(year) == int(candidate_year))
    return title_score, year_score, float(record.get("score") or 0.0)


def _find_episode_for_series(client, series_id: int, season: int, episode: int, *, find_episode) -> dict[str, Any] | None:
    try:
        episodes = client.series_episodes(series_id, language=client.config.language)
        selected = find_episode(episodes, season, episode)
        if selected is None and client.config.fallback_language != client.config.language:
            episodes = client.series_episodes(series_id, language=client.config.fallback_language)
            selected = find_episode(episodes, season, episode)
        return selected
    except OnlineMetadataError:
        return None


def _build_suggestion(client, *, path, request, record, series_builder, find_episode) -> EpisodeMetadataSuggestion | None:
    series_id = _int_or_none(record.get("tvdb_id") or record.get("id") or record.get("seriesId"))
    if series_id is None:
        return None
    series = series_builder(request["query"], request["year"], record)
    if series is None:
        return None
    selected = _find_episode_for_series(
        client, series_id, request["season"], request["episode"], find_episode=find_episode
    )
    if selected is None:
        return None
    episode_id = _int_or_none(
        selected.get("id")
        or selected.get("tvdb_id")
        or selected.get("tvdbId")
        or selected.get("episode_id")
    )
    if episode_id is None:
        return None
    title, title_is_fallback = normalize_episode_metadata_title(
        _tvdb_text(selected, "name_translated", "name", "title"),
        request["episode"],
        source_path=path,
    )
    return EpisodeMetadataSuggestion(
        query_series=request["query"],
        series_tmdb_id=series_id,
        episode_tmdb_id=episode_id,
        show_name=series.name,
        original_show_name=series.original_name,
        season_number=request["season"],
        episode_number=request["episode"],
        title=title,
        first_air_year=series.first_air_year,
        overview=_tvdb_text(selected, "overview", "overview_translated"),
        air_date=str(selected.get("aired") or selected.get("firstAired") or selected.get("air_date") or "").strip(),
        runtime_min=_int_or_none(selected.get("runtime") or selected.get("runtime_min")),
        vote_average=_float_or_none(selected.get("score")),
        provider="thetvdb",
        series_provider_id=series_id,
        episode_provider_id=episode_id,
        title_is_fallback=title_is_fallback,
    )


def resolve_episode_candidates(
    client,
    path: str | Path,
    *,
    limit: int = 6,
    series_builder,
    find_episode,
) -> tuple[EpisodeMetadataSuggestion, ...]:
    request = _candidate_request(path)
    if request is None:
        return ()
    records = _collect_records(client, request)
    if not records:
        return ()

    ranked = sorted(
        records,
        key=lambda record: _record_rank(client, record, query=request["query"], year=request["year"]),
        reverse=True,
    )
    suggestions: list[EpisodeMetadataSuggestion] = []
    cap = max(1, int(limit))
    for record in ranked:
        if _record_rank(client, record, query=request["query"], year=request["year"])[0] < request["title_floor"]:
            continue
        suggestion = _build_suggestion(
            client,
            path=path,
            request=request,
            record=record,
            series_builder=series_builder,
            find_episode=find_episode,
        )
        if suggestion is not None:
            suggestions.append(suggestion)
        if len(suggestions) >= cap:
            break
    return tuple(suggestions)


__all__ = ["resolve_episode_candidates"]
