# -*- coding: utf-8 -*-
"""Public series preflight-metadata facade."""
from __future__ import annotations

from .preflight_metadata_common import MetadataLookupCache, safe_year
from .preflight_metadata_series_resolver import SeriesMetadataResolver, database_payload
from .preflight_metadata_series_sources import (
    SeriesDatabaseLookup,
    SeriesFolderLookup,
    SeriesOnlineLookup,
)

# Compatibility name retained for older tests/extensions.
_database_result = database_payload


def resolve_series_metadata(
    payload,
    *,
    settings,
    online_enabled: bool,
    cache: MetadataLookupCache,
    find_series_dir_from_settings,
    find_series_dir_candidates,
    suggest_series_metadata_for_name,
):
    info = payload if isinstance(payload, dict) else {"base": "", "series_name": str(payload)}
    series_name = str(info.get("series_name") or "").strip()
    if not series_name:
        return {"__local_series_missing__": True} if not online_enabled else None

    search_bases = info.get("search_bases") or []
    if not isinstance(search_bases, list) or not search_bases:
        search_bases = [{"type": "", "base": str(info.get("base") or "")}]
    desired_year = safe_year(info.get("year")) or safe_year(series_name)
    db_bases = [
        (str(base.get("base") or ""), str(base.get("type") or ""))
        for base in search_bases
        if isinstance(base, dict) and str(base.get("base") or "")
    ]

    resolver = SeriesMetadataResolver(
        series_name=series_name,
        desired_year=desired_year,
        online_enabled=online_enabled,
        database=SeriesDatabaseLookup(
            settings, series_name, db_bases, cache, find_series_dir_from_settings
        ),
        folders=SeriesFolderLookup(search_bases, cache, find_series_dir_candidates),
        online=SeriesOnlineLookup(
            settings, series_name, cache, suggest_series_metadata_for_name
        ),
    )
    return resolver.resolve()
