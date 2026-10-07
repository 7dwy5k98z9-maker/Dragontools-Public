# -*- coding: utf-8 -*-
"""Session-level candidate-search cache for TMDB renamer/episode resolution."""
from __future__ import annotations

from copy import deepcopy
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
        return None if value is None else deepcopy(value)

    if lock is not None:
        with lock:
            existing = cached_value()
    else:
        existing = cached_value()
    if existing is not None:
        return existing

    records: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    errors: list[OnlineMetadataError] = []
    successful_calls = 0

    def search(term: str, search_year: int | None, *, language: str | None = None):
        nonlocal successful_calls
        try:
            found = client.search_tv(term, year=search_year, language=language)
        except OnlineMetadataError as exc:
            errors.append(exc)
            return None
        successful_calls += 1
        return found

    def collect(term: str, search_year: int | None) -> None:
        found = search(term, search_year)
        if found is not None and not found and client.config.fallback_language != client.config.language:
            fallback = search(
                term,
                search_year,
                language=client.config.fallback_language,
            )
            if fallback is not None:
                found = fallback
        if found is None:
            return
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

    if successful_calls == 0 and errors:
        raise errors[-1]

    # A partial/transient provider failure must never become a durable empty
    # session-cache hit.  Return any useful partial records, but retry the
    # failed dimensions on the next request.
    if cache is not None and not errors:
        payload = deepcopy(records)
        if lock is not None:
            with lock:
                cache[cache_key] = payload
        else:
            cache[cache_key] = payload
    return records


__all__ = ["collect_episode_candidate_records"]
