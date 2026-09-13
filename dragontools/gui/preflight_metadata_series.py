# -*- coding: utf-8 -*-
"""Serienauflösung für den Preflight-Metadatenlookup."""
from __future__ import annotations

from .preflight_metadata_common import (
    MetadataLookupCache,
    existing_series_payload,
    safe_year,
    series_choices_payload,
    series_folder_choices,
)


def _database_result(match: dict | None, series_name: str) -> dict | None:
    if not match:
        return None
    unusable = str(match.get("unusable_reason") or "")
    if unusable:
        return {
            "__library_path_warning__": unusable,
            "base": match.get("base", ""),
            "base_type": match.get("base_type", ""),
            "series_name": series_name,
            "suggested_series_name": match.get("suggested_series_name", ""),
        }
    if not match.get("series_dir"):
        return None
    note = str(match.get("mapping_notice") or "").strip() or (
        "DB-Pfad entspricht dem aktuell konfigurierten Speicherpfad und wurde vor dem Verschieben geprüft."
    )
    return {
        "__existing_series_dir__": match.get("series_dir", ""),
        "base": match.get("base", ""),
        "base_type": match.get("base_type", ""),
        "series_name": series_name,
        "source": match.get("source", "database"),
        "notice": note,
    }


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
    search_bases = info.get("search_bases") or []
    if not isinstance(search_bases, list) or not search_bases:
        search_bases = [{"type": "", "base": str(info.get("base") or "")}]
    desired_year = safe_year(info.get("year")) or safe_year(series_name)
    db_bases = [
        (str(base.get("base") or ""), str(base.get("type") or ""))
        for base in search_bases
        if isinstance(base, dict) and str(base.get("base") or "")
    ]

    def database_lookup(year: int | None):
        key = (series_name.casefold(), year, tuple(db_bases))
        if key not in cache.library_series:
            cache.library_series[key] = find_series_dir_from_settings(
                settings,
                series_name,
                db_bases,
                year=year,
                dir_exists=cache.directory_exists,
            )
        return cache.library_series[key]

    def online_lookup(year: int | None):
        key = (series_name.casefold(), year)
        if key not in cache.online_series:
            cache.online_series[key] = suggest_series_metadata_for_name(series_name, settings)
        return cache.online_series[key]

    if not series_name:
        return {"__local_series_missing__": True} if not online_enabled else None

    library_match = database_lookup(desired_year)
    direct = _database_result(library_match, series_name)
    if direct:
        return direct

    early_suggestion = None
    # Ein mehrdeutiger DB-Treffer darf nicht zuerst einen NAS-Ordnerscan
    # erzwingen. Online nur das Jahr bestimmen und die DB erneut fragen.
    if library_match and library_match.get("ambiguous_years") and not desired_year and online_enabled:
        early_suggestion = online_lookup(None)
        desired_year = safe_year(getattr(early_suggestion, "first_air_year", None))
        if desired_year:
            direct = _database_result(database_lookup(desired_year), series_name)
            if direct:
                return direct

    if desired_year:
        choices = series_folder_choices(
            find_series_dir_candidates, series_name, search_bases, desired_year, cache
        )
        if len(choices) == 1:
            return existing_series_payload(choices[0], series_name)
        if len(choices) > 1:
            return series_choices_payload(choices, series_name)

    raw_choices = series_folder_choices(
        find_series_dir_candidates, series_name, search_bases, None, cache
    )
    if len(raw_choices) == 1:
        return existing_series_payload(raw_choices[0], series_name)

    if len(raw_choices) > 1:
        if not online_enabled:
            return series_choices_payload(raw_choices, series_name)
        suggestion = early_suggestion or online_lookup(desired_year)
        suggestion_year = safe_year(getattr(suggestion, "first_air_year", None))
        suggested_name = str(getattr(suggestion, "folder_name", "") or "")
        if suggestion_year:
            choices = series_folder_choices(
                find_series_dir_candidates, series_name, search_bases, suggestion_year, cache
            )
            if not choices and suggested_name:
                choices = series_folder_choices(
                    find_series_dir_candidates, suggested_name, search_bases, suggestion_year, cache
                )
            if len(choices) == 1:
                return existing_series_payload(choices[0], series_name)
            if len(choices) > 1:
                return series_choices_payload(choices, series_name, suggested_name)
        return series_choices_payload(raw_choices, series_name, suggested_name)

    if online_enabled:
        return early_suggestion or online_lookup(desired_year)
    return {"__local_series_missing__": True}
