# -*- coding: utf-8 -*-
"""Session-level TheTVDB candidate-search cache for mass renaming."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .online_metadata_tvdb_helpers import _tvdb_record_id
from .online_metadata_common import OnlineMetadataError, _int_or_none, compare_metadata_text


def _search_languages(client) -> tuple[str, ...]:
    primary = client.config.language
    fallback = client.config.fallback_language
    return (primary,) if fallback == primary else (primary, fallback)


def collect_candidate_records(client, request: dict[str, Any]) -> list[dict[str, Any]]:
    cache = getattr(client, "_renamer_search_cache", None)
    lock = getattr(client, "_episode_batch_lock", None)
    cache_key = (
        compare_metadata_text(str(request["query"])),
        int(request["year"]) if request["year"] is not None else None,
        tuple(str(term) for term in request["search_terms"]),
        bool(request["retry_without_year"]),
        tuple(_search_languages(client)),
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

    def collect(term: str, year: int | None) -> None:
        nonlocal successful_calls
        found: list[dict[str, Any]] = []
        for language in _search_languages(client):
            try:
                current = client.search_series(term, year=year, language=language)
            except OnlineMetadataError as exc:
                errors.append(exc)
                continue
            successful_calls += 1
            found = current
            if found:
                break
        for record in found or []:
            record_id = _tvdb_record_id(record)
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

    if successful_calls == 0 and errors:
        raise errors[-1]

    if cache is not None and not errors:
        payload = deepcopy(records)
        if lock is not None:
            with lock:
                cache[cache_key] = payload
        else:
            cache[cache_key] = payload
    return records


__all__ = ["collect_candidate_records"]
