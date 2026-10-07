# -*- coding: utf-8 -*-
"""Gemeinsame Datenstrukturen und Hilfen für den Preflight-Metadatenlookup."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Callable

from ..core.path_syntax import path_compare_key, normalize_user_path


def safe_year(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        match = re.search(r"\((19\d{2}|20\d{2})\)\s*$", str(value or "").strip())
        return int(match.group(1)) if match else None
    return number if 1900 <= number <= 2099 else None


def existing_series_payload(choice: dict, series_name: str, source: str = "folder_search", notice: str = "") -> dict:
    return {
        "__existing_series_dir__": choice.get("path", ""),
        "base": choice.get("base", ""),
        "base_type": choice.get("base_type", ""),
        "series_name": series_name,
        "source": source,
        "notice": notice,
    }


def series_choices_payload(choices: list[dict], series_name: str, suggested_series_name: str = "") -> dict:
    return {
        "__series_dir_choices__": choices,
        "series_name": series_name,
        "suggested_series_name": suggested_series_name,
    }


def existing_movie_payload(match: dict, movie_name: str) -> dict:
    return {
        "__existing_movie_dir__": match.get("movie_dir", ""),
        "base": match.get("base", ""),
        "movie_name": movie_name or match.get("suggested_movie_name", ""),
        "source": match.get("source", "database"),
        "notice": match.get("mapping_notice", ""),
    }


@dataclass
class MetadataLookupCache:
    dir_exists: dict[str, bool] = field(default_factory=dict)
    folders: dict[tuple[str, str, int | None], list[str]] = field(default_factory=dict)
    library_series: dict[tuple[str, int | None, tuple[tuple[str, str], ...]], dict | None] = field(default_factory=dict)
    library_movies: dict[tuple[str, int | None, tuple[tuple[str, str], ...]], dict | None] = field(default_factory=dict)
    online_movies: dict[str, object] = field(default_factory=dict)
    online_series: dict[tuple[str, int | None], object] = field(default_factory=dict)

    def directory_exists(self, value: str) -> bool:
        text = normalize_user_path(str(value or "").strip())
        if not text:
            return False
        key = path_compare_key(text)
        if key not in self.dir_exists:
            try:
                self.dir_exists[key] = Path(text).is_dir()
            except OSError:
                self.dir_exists[key] = False
        return self.dir_exists[key]


@dataclass
class MetadataRequestGuard:
    """Generation guard that prevents stale async lookup results from winning.

    A newer lookup for the same widget invalidates every older generation.
    The helper is Qt-free so the concurrency contract can be regression-tested
    without a GUI runtime.
    """

    _generations: dict[int, int] = field(default_factory=dict)

    def begin(self, target: object) -> int:
        key = id(target)
        generation = self._generations.get(key, 0) + 1
        self._generations[key] = generation
        return generation

    def is_current(self, target: object, generation: int) -> bool:
        return self._generations.get(id(target), 0) == int(generation)


def metadata_job_identity(job: object) -> tuple[str, str] | None:
    if not isinstance(job, tuple) or len(job) < 2:
        return None
    return str(job[0]), str(job[1])


def series_folder_choices(
    find_candidates: Callable[..., list[str]],
    series_name: str,
    search_bases: list[dict],
    year: int | None,
    cache: MetadataLookupCache,
) -> list[dict]:
    for base_info in search_bases:
        if not isinstance(base_info, dict):
            continue
        base = str(base_info.get("base") or "")
        if not base:
            continue
        cache_key = (base, str(series_name or "").strip().casefold(), year)
        if cache_key not in cache.folders:
            cache.folders[cache_key] = list(find_candidates(base, series_name, year=year) or [])
        candidates = cache.folders[cache_key]
        if candidates:
            base_type = str(base_info.get("type") or "")
            return [{"path": path, "base": base, "base_type": base_type} for path in candidates]
    return []
