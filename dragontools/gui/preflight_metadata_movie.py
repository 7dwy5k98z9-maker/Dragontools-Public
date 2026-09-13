# -*- coding: utf-8 -*-
"""Filmauflösung für den Preflight-Metadatenlookup."""
from __future__ import annotations

from .preflight_metadata_common import MetadataLookupCache, existing_movie_payload, safe_year


def resolve_movie_metadata(
    payload,
    *,
    settings,
    online_enabled: bool,
    cache: MetadataLookupCache,
    parse_movie_query,
    find_movie_dir_from_settings,
    suggest_movie_metadata_for_file,
):
    payload_info = payload if isinstance(payload, dict) else {"path": str(payload), "movie_base": ""}
    source_path = str(payload_info.get("path") or payload or "")
    movie_base = str(payload_info.get("movie_base") or "")
    parsed = parse_movie_query(source_path)
    movie_bases = ((movie_base, "Filme"),) if movie_base else ()

    def library_lookup(year: int | None):
        key = (parsed.title.strip().casefold(), year, movie_bases)
        if key not in cache.library_movies:
            cache.library_movies[key] = find_movie_dir_from_settings(
                settings,
                parsed.title,
                movie_bases,
                year=year,
                dir_exists=cache.directory_exists,
            )
        return cache.library_movies[key]

    def online_lookup():
        if source_path not in cache.online_movies:
            cache.online_movies[source_path] = suggest_movie_metadata_for_file(source_path, settings)
        return cache.online_movies[source_path]

    match = library_lookup(parsed.year)
    if match:
        unusable = str(match.get("unusable_reason") or "")
        if unusable:
            return {
                "__movie_library_warning__": unusable,
                "movie_name": match.get("suggested_movie_name", parsed.title),
            }
        if match.get("movie_dir"):
            return existing_movie_payload(match, str(match.get("suggested_movie_name") or parsed.title))

        # Wenn mehrere Jahrgänge in der DB existieren, zuerst online das Jahr
        # auflösen und die indexierte DB erneut fragen. Kein Ordnerscan nötig.
        if match.get("ambiguous_years") and parsed.year is None and online_enabled:
            suggestion = online_lookup()
            resolved_year = safe_year(getattr(suggestion, "release_year", None))
            if resolved_year:
                year_match = library_lookup(resolved_year)
                if year_match:
                    unusable = str(year_match.get("unusable_reason") or "")
                    if unusable:
                        return {
                            "__movie_library_warning__": unusable,
                            "movie_name": year_match.get("suggested_movie_name", parsed.title),
                        }
                    if year_match.get("movie_dir"):
                        return existing_movie_payload(
                            year_match,
                            str(year_match.get("suggested_movie_name") or parsed.title),
                        )
            return suggestion

    return online_lookup() if online_enabled else None
