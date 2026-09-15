# -*- coding: utf-8 -*-
"""Fail-closed ambiguity classification for automatic NFO metadata."""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable

from ..core.online_metadata import OnlineMetadataError, parse_movie_query, parse_series_query


@dataclass(frozen=True, slots=True)
class MetadataResolution:
    suggestion: object | None
    ambiguous: bool = False
    reason: str = ""
    candidate_count: int = 0


def preferred_clients(client) -> tuple[object, ...]:
    children = tuple(getattr(client, "clients", ()) or ())
    return children or (client,)


def resolve_episode_candidates_for_postprocess(client, path: str, *, limit: int = 4) -> tuple[object, ...]:
    """Use provider priority as fallback semantics, not as competing duplicates."""
    for provider_client in preferred_clients(client):
        try:
            refresh = getattr(provider_client, "refresh_episode_candidates", None)
            if callable(refresh):
                items = tuple(refresh(path, limit=limit) or ())
            else:
                resolve_many = getattr(provider_client, "resolve_episode_candidates", None)
                if callable(resolve_many):
                    items = tuple(resolve_many(path, limit=limit) or ())
                else:
                    resolve_one = getattr(provider_client, "resolve_episode_file", None)
                    item = resolve_one(path) if callable(resolve_one) else None
                    items = (item,) if item is not None else ()
        except OnlineMetadataError:
            continue
        if items:
            return _dedupe_episode_candidates(items)
    return ()


def episode_candidate_buckets_for_postprocess(client, path: str, *, limit: int = 4):
    """Yield one candidate bucket per provider in configured priority order."""
    for provider_client in preferred_clients(client):
        try:
            refresh = getattr(provider_client, "refresh_episode_candidates", None)
            if callable(refresh):
                items = tuple(refresh(path, limit=limit) or ())
            else:
                resolve_many = getattr(provider_client, "resolve_episode_candidates", None)
                if callable(resolve_many):
                    items = tuple(resolve_many(path, limit=limit) or ())
                else:
                    resolve_one = getattr(provider_client, "resolve_episode_file", None)
                    item = resolve_one(path) if callable(resolve_one) else None
                    items = (item,) if item is not None else ()
        except OnlineMetadataError:
            continue
        if items:
            yield provider_client, _dedupe_episode_candidates(items)


def resolve_movie_search_for_postprocess(client, path: str, *, limit: int = 6) -> tuple[dict[str, Any], ...]:
    parsed = parse_movie_query(path)
    if not parsed.title:
        return ()
    for provider_client in preferred_clients(client):
        search = getattr(provider_client, "search_movies", None)
        if not callable(search):
            continue
        try:
            items = list(search(parsed.title, year=parsed.year) or ())
        except OnlineMetadataError:
            continue
        if items:
            return tuple(dict(item) for item in items[: max(2, limit)])
    return ()


def movie_candidate_buckets_for_postprocess(client, path: str, *, limit: int = 6):
    parsed = parse_movie_query(path)
    if not parsed.title:
        return
    for provider_client in preferred_clients(client):
        search = getattr(provider_client, "search_movies", None)
        if not callable(search):
            continue
        try:
            items = list(search(parsed.title, year=parsed.year) or ())
        except OnlineMetadataError:
            continue
        if items:
            yield provider_client, tuple(dict(item) for item in items[: max(2, limit)])


def episode_resolution(candidates: Iterable[object], path: str) -> MetadataResolution:
    items = tuple(candidates)
    if not items:
        return MetadataResolution(None, False, "Keine passende Serienfolge gefunden.", 0)
    parsed = parse_series_query(path)
    ranked = sorted(
        ((candidate, _series_score(parsed.title, parsed.year, candidate)) for candidate in items),
        key=lambda pair: pair[1],
        reverse=True,
    )
    return _finish_resolution(ranked, kind="Serienfolge")


def movie_ambiguity(records: Iterable[dict[str, Any]], path: str) -> MetadataResolution:
    items = tuple(records)
    if not items:
        return MetadataResolution(None, True, "Eindeutigkeit des Film-Treffers konnte nicht geprüft werden.", 0)
    parsed = parse_movie_query(path)
    ranked = sorted(
        ((record, _movie_score(parsed.title, parsed.year, record)) for record in items),
        key=lambda pair: pair[1],
        reverse=True,
    )
    result = _finish_resolution(ranked, kind="Film")
    # Raw provider records are used only for ambiguity. The normal resolver
    # still builds the rich MovieMetadataSuggestion afterwards.
    return MetadataResolution(None, result.ambiguous, result.reason, result.candidate_count)


def _finish_resolution(ranked: list[tuple[object, float]], *, kind: str) -> MetadataResolution:
    if not ranked:
        return MetadataResolution(None, False, f"Kein passender {kind}-Treffer gefunden.", 0)
    best, best_score = ranked[0]
    if best_score < 0.72:
        return MetadataResolution(None, True, f"{kind}-Treffer ist nicht sicher genug ({best_score:.0%}).", len(ranked))
    if len(ranked) > 1:
        second_score = ranked[1][1]
        if second_score >= best_score - 0.08:
            return MetadataResolution(
                None,
                True,
                f"{kind}-Treffer ist mehrdeutig ({best_score:.0%} vs. {second_score:.0%}).",
                len(ranked),
            )
    return MetadataResolution(best, False, "", len(ranked))


def _series_score(query: str, query_year: int | None, candidate: object) -> float:
    # ``query_series`` is the search term DragonTools itself sent to the
    # provider.  Comparing the query with itself would turn an unrelated
    # single provider result into a false 100 % match.  Only provider-owned
    # titles may contribute to confidence.
    names = [
        str(getattr(candidate, "show_name", "") or ""),
        str(getattr(candidate, "original_show_name", "") or ""),
    ]
    score = max((_text_score(query, name) for name in names if name), default=0.0)
    year = _int_or_none(getattr(candidate, "first_air_year", None))
    return _apply_year(score, query_year, year)


def _movie_score(query: str, query_year: int | None, record: dict[str, Any]) -> float:
    titles = [
        str(record.get("title") or ""),
        str(record.get("name") or ""),
        str(record.get("original_title") or record.get("originalName") or ""),
        str(record.get("name_translated") or record.get("title_translated") or ""),
    ]
    score = max((_text_score(query, title) for title in titles if title), default=0.0)
    year = _record_year(record)
    return _apply_year(score, query_year, year)


def _apply_year(score: float, expected: int | None, actual: int | None) -> float:
    if expected and actual:
        score += 0.18 if expected == actual else -min(0.20, abs(expected - actual) * 0.04)
    elif expected or actual:
        score -= 0.03
    return max(0.0, min(1.0, score))


def _text_score(left: str, right: str) -> float:
    a, b = _norm(left), _norm(right)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _norm(value: str) -> str:
    text = str(value or "").casefold().replace("&", " und ")
    text = text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text)).strip()


def _record_year(record: dict[str, Any]) -> int | None:
    for key in ("release_date", "first_air_date", "firstAired", "year"):
        value = record.get(key)
        match = re.search(r"(?:19|20)\d{2}", str(value or ""))
        if match:
            return int(match.group(0))
    return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _dedupe_episode_candidates(items: Iterable[object]) -> tuple[object, ...]:
    unique: list[object] = []
    seen: set[tuple] = set()
    for item in items:
        key = (
            str(getattr(item, "provider", "") or ""),
            getattr(item, "series_provider_id", None) or getattr(item, "series_tmdb_id", None),
            int(getattr(item, "season_number", 0) or 0),
            int(getattr(item, "episode_number", 0) or 0),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return tuple(unique)
