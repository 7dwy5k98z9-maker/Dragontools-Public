# -*- coding: utf-8 -*-
"""Session-level candidate-search cache for TMDB renamer/episode resolution."""
from __future__ import annotations

from typing import Any

from .online_metadata_common import OnlineMetadataError, _int_or_none, compare_metadata_text


def collect_episode_candidate_records(
    client,
    query: str,
    *,
    year: int | None,
    search_terms: list[str] | tuple[str, ...],
    retry_without_year: bool,
) -> list[dict[str, Any]]:
    cache = getattr(client, "_renamer_search_cache", None)
    lock = getattr(client, "_renamer_batch_lock", None)
    cache_key = (
        compare_metadata_text(query),
        int(year) if year is not None else None,
        tuple(str(term) for term in search_terms),
        bool(retry_without_year),
        str(client.config.language),
        str(client.config.fallback_language),
    )

    def cached_value() -> list[dict[str, Any]] | None:
        if cache is None:
            return None
        value = cache.get(cache_key)
        return None if value is None else [dict(item) for item in value]

    if lock is not None:
        with lock:
            existing = cached_value()
    else:
        existing = cached_value()
    if existing is not None:
        return existing

    records: list[dict[str, Any]] = []
    seen_ids: set[int] = set()

    def collect(term: str, search_year: int | None) -> None:
        try:
            found = client.search_tv(term, year=search_year)
            if not found and client.config.fallback_language != client.config.language:
                found = client.search_tv(
                    term,
                    year=search_year,
                    language=client.config.fallback_language,
                )
        except OnlineMetadataError:
            found = []
        for record in found or []:
            record_id = _int_or_none(record.get("id"))
            if record_id is None or record_id in seen_ids:
                continue
            seen_ids.add(record_id)
            records.append(record)

    for term in search_terms[:2]:
        collect(term, year)
        if year is not None and retry_without_year:
            collect(term, None)
    for term in search_terms[2:]:
        collect(term, None)

    if cache is not None:
        payload = [dict(item) for item in records]
        if lock is not None:
            with lock:
                cache[cache_key] = payload
        else:
            cache[cache_key] = payload
    return records


__all__ = ["collect_episode_candidate_records"]
