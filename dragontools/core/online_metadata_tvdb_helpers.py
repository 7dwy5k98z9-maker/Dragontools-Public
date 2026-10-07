# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from .online_metadata_identity import provider_id
from typing import Any

from .online_metadata_tvdb_localization import (
    _tvdb_language_candidates, _tvdb_localized_title, _tvdb_localized_overview,
    _tvdb_text, _metadata_text_value, _tvdb_language_code,
)
from .online_metadata_common import (
    _int_or_none,
    _year_from_date,
    compare_metadata_text,
    normalize_episode_metadata_title,
)

def _records_from_data(data: dict[str, Any]) -> list[dict[str, Any]]:
    records = data.get("data") if isinstance(data, dict) else []
    if isinstance(records, dict):
        records = records.get("results") or records.get("items") or []
    if not isinstance(records, list):
        return []
    return [dict(item) for item in records if isinstance(item, dict)]


def _single_record_from_data(data: dict[str, Any]) -> dict[str, Any] | None:
    record = data.get("data") if isinstance(data, dict) else None
    return dict(record) if isinstance(record, dict) else None


def _episodes_from_tvdb_response(data: dict[str, Any]) -> list[dict[str, Any]]:
    payload = data.get("data") if isinstance(data, dict) else None
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        episodes = payload.get("episodes") or payload.get("data") or []
        if isinstance(episodes, list):
            return [dict(item) for item in episodes if isinstance(item, dict)]
    return []


def _tvdb_record_id(record: dict[str, Any]) -> int | None:
    for key in ("tvdb_id", "tvdbId", "id", "movieId", "seriesId", "objectID", "object_id", "provider_id"):
        value = record.get(key)
        numeric = provider_id(value)
        if numeric is not None:
            return numeric
        match = re.fullmatch(r"(?:series|movie|episode)-(\d+)", str(value or ""))
        if match:
            return provider_id(match.group(1))
    return None


def _tvdb_remote_id(record: dict[str, Any], provider: str) -> str:
    wanted = str(provider or "").strip().lower()
    for key in ("remoteIds", "remote_ids"):
        remote_ids = record.get(key)
        if not isinstance(remote_ids, list):
            continue
        for item in remote_ids:
            if not isinstance(item, dict):
                continue
            source = str(
                item.get("sourceName")
                or item.get("source")
                or item.get("type")
                or item.get("provider")
                or ""
            ).lower()
            if wanted and wanted not in source:
                continue
            remote_id = str(item.get("id") or item.get("remoteId") or item.get("remote_id") or "").strip()
            if remote_id:
                return remote_id
    return ""













def _year_from_tvdb_record(record: dict[str, Any]) -> int | None:
    for key in ("year", "firstAired", "first_air_date", "releaseDate", "aired"):
        year = _year_from_date(record.get(key))
        if year:
            return year
    return None


def _episode_title_is_fallback(
    record: dict[str, Any] | None,
    episode: int,
    *,
    source_path: Any = None,
) -> bool:
    if not isinstance(record, dict):
        return True
    _title, is_fallback = normalize_episode_metadata_title(
        _tvdb_text(record, "name_translated", "name", "title"),
        episode,
        source_path=source_path,
    )
    return is_fallback


def _merge_episode_language_fallback(
    primary: dict[str, Any],
    fallback: dict[str, Any],
    episode: int,
) -> dict[str, Any]:
    """Keep localized primary metadata but take a real title from fallback."""
    merged = dict(fallback or {})
    for key, value in (primary or {}).items():
        if value not in (None, "", [], {}):
            merged[key] = value
    fallback_title, fallback_is_generic = normalize_episode_metadata_title(
        _tvdb_text(fallback or {}, "name_translated", "name", "title"),
        episode,
    )
    if not fallback_is_generic:
        merged["name_translated"] = fallback_title
        merged["name"] = fallback_title
        merged["title"] = fallback_title
    return merged
