# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Iterable

from .german_title_variants import fold_german_umlauts, german_umlaut_search_variants
from .movie_renamer_models import (
    MovieRenameCandidate,
    MovieSearchResolver,
    ParsedSeriesReleaseName,
    SeriesRenameCandidate,
    SeriesSearchResolver,
)
from .movie_renamer_parsing import _YEAR_RE
from .online_metadata_common import default_episode_title, normalize_episode_metadata_title
from ..rules.renamer_rules import apply_title_exception

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
    if client is None:
        return ()
    if hasattr(client, "search_movies"):
        results = []
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
        return results or ()
    return ()


def _resolve_series_results(
    parsed: ParsedSeriesReleaseName,
    *,
    resolver: SeriesSearchResolver | None,
    client: Any | None,
) -> Iterable[Any]:
    if resolver is not None:
        return resolver(parsed.series, parsed.season, parsed.episode, parsed.year) or ()
    if client is None:
        return ()
    lookup_name = f"{parsed.series}"
    if parsed.year:
        lookup_name += f" ({parsed.year})"
    lookup_name += f" - S{parsed.season:02d}E{parsed.episode:02d}{parsed.suffix or '.mkv'}"
    lookup_path = Path(lookup_name)
    if hasattr(client, "resolve_episode_candidates"):
        suggestions = client.resolve_episode_candidates(lookup_path, limit=6)
        if suggestions:
            return suggestions
    if hasattr(client, "resolve_episode_file"):
        suggestion = client.resolve_episode_file(lookup_path)
        if suggestion is not None:
            return (suggestion,)
    if hasattr(client, "resolve_series"):
        series = client.resolve_series(parsed.series, year=parsed.year)
        if series is not None:
            return (series,)
    return ()


def _candidate_from_result(raw: Any, query_title: str, query_year: int | None) -> MovieRenameCandidate | None:
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
        title = str(raw.get("title") or raw.get("name_translated") or raw.get("name") or raw.get("original_title") or "").strip()
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
    score = _candidate_score(query_title, query_year, title, parsed_year)
    return MovieRenameCandidate(
        title=title,
        year=parsed_year,
        tmdb_id=tmdb_id,
        original_title=original_title,
        provider=provider,
        provider_id=provider_id,
        score=score,
    )


def _series_candidate_from_result(
    raw: Any,
    parsed: ParsedSeriesReleaseName,
    *,
    title_exception: Callable[[str], str] = apply_title_exception,
) -> SeriesRenameCandidate | None:
    if raw is None:
        return None

    title_is_fallback = False
    episode_verified = False

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
        episode_verified = episode_id is not None and episode_id > 0
        year = _int_or_none(getattr(raw, "first_air_year", None)) or parsed.year
        score = _series_score(parsed, series, season, episode, title, year)
    elif hasattr(raw, "name") and hasattr(raw, "first_air_year"):
        # Nur die Serie wurde gefunden; die Episode selbst ist beim Provider noch
        # nicht vorhanden. Der lokale Release-Dateiname ist dann KEINE valide
        # Episodentitel-Quelle.
        series = str(getattr(raw, "name", "") or parsed.series).strip()
        season = parsed.season
        episode = parsed.episode
        title = default_episode_title(episode)
        title_is_fallback = True
        provider = str(getattr(raw, "provider", "") or "metadata")
        provider_id = _int_or_none(getattr(raw, "provider_id", None) or getattr(raw, "tmdb_id", None))
        episode_id = None
        year = _int_or_none(getattr(raw, "first_air_year", None)) or parsed.year
        score = _series_score(parsed, series, season, episode, title, year)
    elif isinstance(raw, dict):
        series = str(raw.get("series") or raw.get("show_name") or raw.get("name") or parsed.series).strip()
        season = _int_or_none(raw.get("season") or raw.get("season_number")) or parsed.season
        episode = _int_or_none(raw.get("episode") or raw.get("episode_number")) or parsed.episode
        raw_title = raw.get("episode_title") if "episode_title" in raw else raw.get("title")
        title, derived_fallback = normalize_episode_metadata_title(
            raw_title,
            episode,
            source_path=parsed.source_name,
        )
        title_is_fallback = bool(raw.get("title_is_fallback", False)) or derived_fallback
        provider = str(raw.get("provider") or "metadata")
        provider_id = _int_or_none(raw.get("provider_id") or raw.get("series_id") or raw.get("tmdb_id"))
        episode_id = _int_or_none(raw.get("episode_id") or raw.get("episode_provider_id") or raw.get("episode_tmdb_id"))
        episode_verified = episode_id is not None and episode_id > 0
        year = _int_or_none(raw.get("year") or raw.get("first_air_year")) or parsed.year
        score = _series_score(parsed, series, season, episode, title, year)
    else:
        return None

    # Fuzzy-Suchvarianten dürfen den Vertrauenswert NICHT künstlich auf 100 %
    # anheben. Bewertet wird immer der ursprünglich erkannte Serientitel gegen
    # den tatsächlich gefundenen Online-Titel.
    match_reason = ""
    alias_title = title_exception(parsed.series).strip()
    if _compare_text(alias_title) != _compare_text(parsed.series):
        alias_similarity = _series_title_similarity(alias_title, series)
        # Eine explizite Nutzerregel ist bewusst vertrauenswürdig, aber nur,
        # wenn der gefundene Online-Titel praktisch dem definierten Alias entspricht.
        if alias_similarity >= 0.98:
            score = 1.0
            match_reason = "Aliasregel"

    # Ein fehlender/generischer Episodentitel ist kein Widerspruch, aber auch
    # keine Bestätigung. Deshalb darf dieser Fall nie als 100-%-Treffer erscheinen.
    if title_is_fallback:
        confidence_cap = 0.92 if episode_verified else 0.85
        score = min(score, confidence_cap)
        match_reason = (
            "Episodentitel offen"
            if episode_verified
            else "Episode noch nicht in Metadaten"
        )

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


def _series_title_similarity(source_title: str, candidate_title: str) -> float:
    # DragonTools patch: fuzzy display confidence v6
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


def _series_score(parsed: ParsedSeriesReleaseName, series: str, season: int, episode: int, title: str, candidate_year: int | None = None) -> float:
    # Angezeigte Sicherheit = echte Titelähnlichkeit.
    # Staffel/Folge werden von TMDB/TheTVDB bereits als Existenzprüfung validiert.
    # Deshalb gibt es dafür KEINEN positiven Bonus mehr. Nur echte Abweichungen
    # werden bestraft, damit externe/custom Resolver weiterhin sicher bleiben.
    ratio = _series_title_similarity(parsed.series, series)
    if int(season) != int(parsed.season):
        ratio -= 0.25
    if int(episode) != int(parsed.episode):
        ratio -= 0.25
    return max(0.0, min(1.0, ratio))


def _sort_candidates(candidates: list[Any], *, client: Any | None) -> list[Any]:
    # Eine explizite Aliasregel ist eine bewusste Benutzerentscheidung und hat
    # deshalb Vorrang vor einem normalen, zufaellig ebenfalls exakten Treffer.
    # Innerhalb derselben Alias-Stufe entscheiden Match-Qualitaet und danach die
    # Provider-Praeferenz.
    provider_order = tuple(getattr(client, "provider_order", ()) or ())
    rank = {str(provider).lower(): idx for idx, provider in enumerate(provider_order)}
    fallback_rank = len(rank)

    return sorted(
        candidates,
        key=lambda item: (
            0 if str(getattr(item, "match_reason", "") or "") == "Aliasregel" else 1,
            -float(getattr(item, "score", 0.0) or 0.0),
            rank.get(str(getattr(item, "provider", "") or "").lower(), fallback_rank),
            str(getattr(item, "series", getattr(item, "title", "")) or "").lower(),
        ),
    )


def _limit_candidates_with_provider_coverage(
    candidates: list[Any],
    *,
    client: Any | None,
    limit: int,
) -> list[Any]:
    # limit gilt JE Provider; Score-Reihenfolge bleibt erhalten.
    per_provider_cap = max(1, int(limit))
    ordered = _sort_candidates(candidates, client=client)
    provider_order = tuple(
        str(provider or "").strip().lower()
        for provider in (getattr(client, "provider_order", ()) or ())
        if str(provider or "").strip()
    )

    if len(provider_order) < 2:
        return ordered[:per_provider_cap]

    counts: dict[str, int] = {}
    selected: list[Any] = []

    for item in ordered:
        provider = str(getattr(item, "provider", "") or "").strip().lower() or "metadata"
        if counts.get(provider, 0) >= per_provider_cap:
            continue
        selected.append(item)
        counts[provider] = counts.get(provider, 0) + 1

    return selected


def _candidate_score(query_title: str, query_year: int | None, result_title: str, result_year: int | None) -> float:
    query_norm = _compare_text(query_title)
    result_norm = _compare_text(result_title)
    ratio = SequenceMatcher(None, query_norm, result_norm).ratio()
    ratio = max(ratio, SequenceMatcher(None, _drop_leading_article(query_norm), _drop_leading_article(result_norm)).ratio())
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
