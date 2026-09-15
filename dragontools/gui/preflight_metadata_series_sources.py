# -*- coding: utf-8 -*-
"""Focused lookup sources used by the series metadata preflight."""
from __future__ import annotations

from dataclasses import dataclass

from .preflight_metadata_common import MetadataLookupCache, series_folder_choices


@dataclass(slots=True)
class SeriesDatabaseLookup:
    settings: object
    series_name: str
    db_bases: list[tuple[str, str]]
    cache: MetadataLookupCache
    find_series_dir_from_settings: object

    def lookup(self, year: int | None):
        key = (self.series_name.casefold(), year, tuple(self.db_bases))
        if key not in self.cache.library_series:
            self.cache.library_series[key] = self.find_series_dir_from_settings(
                self.settings,
                self.series_name,
                self.db_bases,
                year=year,
                dir_exists=self.cache.directory_exists,
            )
        return self.cache.library_series[key]


@dataclass(slots=True)
class SeriesOnlineLookup:
    settings: object
    series_name: str
    cache: MetadataLookupCache
    suggest_series_metadata_for_name: object

    def lookup(self, year: int | None):
        key = (self.series_name.casefold(), year)
        if key not in self.cache.online_series:
            try:
                value = self.suggest_series_metadata_for_name(
                    self.series_name,
                    self.settings,
                    year=year,
                )
            except TypeError as exc:
                # Compatibility with older extension/test callbacks.
                if "year" not in str(exc):
                    raise
                value = self.suggest_series_metadata_for_name(self.series_name, self.settings)
            self.cache.online_series[key] = value
        return self.cache.online_series[key]


@dataclass(slots=True)
class SeriesFolderLookup:
    search_bases: list
    cache: MetadataLookupCache
    find_series_dir_candidates: object

    def choices(self, name: str, year: int | None):
        return series_folder_choices(
            self.find_series_dir_candidates,
            name,
            self.search_bases,
            year,
            self.cache,
        )
