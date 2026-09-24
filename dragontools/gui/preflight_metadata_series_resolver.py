# -*- coding: utf-8 -*-
"""Orchestrates DB, folder and online resolution for series preflight metadata."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .preflight_metadata_common import (
    existing_series_payload,
    safe_year,
    series_choices_payload,
)
from .preflight_metadata_series_sources import (
    SeriesDatabaseLookup,
    SeriesFolderLookup,
    SeriesOnlineLookup,
)


def database_payload(match: dict | None, series_name: str) -> dict | None:
    """Translate a DB lookup result into the public preflight payload."""
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


@dataclass(slots=True)
class SeriesMetadataResolver:
    """Resolve one series against DB, existing folders and online metadata."""

    series_name: str
    desired_year: int | None
    online_enabled: bool
    database: SeriesDatabaseLookup
    folders: SeriesFolderLookup
    online: SeriesOnlineLookup

    def resolve(self) -> Any:
        library_match = self.database.lookup(self.desired_year)
        direct = database_payload(library_match, self.series_name)
        library_warning = (
            direct
            if isinstance(direct, dict) and "__library_path_warning__" in direct
            else None
        )
        # Ein nicht erreichbarer/staler DB-Treffer ist nur ein Hinweis. Er darf
        # die eigentliche Ordner- und Online-Metadatensuche (inkl. Serienjahr)
        # nicht vorzeitig beenden. Nur ein nutzbarer DB-Pfad ist terminal.
        if direct and library_warning is None:
            return direct

        early_suggestion = self._resolve_ambiguous_database_year(library_match)
        direct = self._retry_database_after_online_year(early_suggestion)
        if direct and "__library_path_warning__" not in direct:
            return direct
        if isinstance(direct, dict) and "__library_path_warning__" in direct:
            library_warning = direct

        by_year = self._resolve_folders_for_known_year()
        if by_year is not None:
            return by_year

        raw_choices = self.folders.choices(self.series_name, None)
        local = self._resolve_raw_folder_choices(raw_choices, early_suggestion)
        if local is not None:
            return local

        if self.online_enabled:
            suggestion = early_suggestion or self.online.lookup(self.desired_year)
            if suggestion is not None and library_warning is not None:
                result = dict(library_warning)
                result["__online_series_suggestion__"] = suggestion
                return result
            return suggestion or library_warning
        return library_warning or {"__local_series_missing__": True}

    def _resolve_ambiguous_database_year(self, library_match: dict | None):
        if not (
            library_match
            and library_match.get("ambiguous_years")
            and not self.desired_year
            and self.online_enabled
        ):
            return None
        suggestion = self.online.lookup(None)
        resolved_year = safe_year(getattr(suggestion, "first_air_year", None))
        if resolved_year:
            self.desired_year = resolved_year
        return suggestion

    def _retry_database_after_online_year(self, suggestion) -> dict | None:
        if suggestion is None or not self.desired_year:
            return None
        return database_payload(self.database.lookup(self.desired_year), self.series_name)

    def _resolve_folders_for_known_year(self):
        if not self.desired_year:
            return None
        choices = self.folders.choices(self.series_name, self.desired_year)
        if len(choices) == 1:
            return existing_series_payload(choices[0], self.series_name)
        if len(choices) > 1:
            return series_choices_payload(choices, self.series_name)
        return None

    def _resolve_raw_folder_choices(self, raw_choices: list, early_suggestion):
        if len(raw_choices) == 1:
            return existing_series_payload(raw_choices[0], self.series_name)
        if len(raw_choices) <= 1:
            return None
        if not self.online_enabled:
            return series_choices_payload(raw_choices, self.series_name)

        suggestion = early_suggestion or self.online.lookup(self.desired_year)
        suggestion_year = safe_year(getattr(suggestion, "first_air_year", None))
        suggested_name = str(getattr(suggestion, "folder_name", "") or "")
        if suggestion_year:
            choices = self.folders.choices(self.series_name, suggestion_year)
            if not choices and suggested_name:
                choices = self.folders.choices(suggested_name, suggestion_year)
            if len(choices) == 1:
                return existing_series_payload(choices[0], self.series_name)
            if len(choices) > 1:
                return series_choices_payload(choices, self.series_name, suggested_name)
        return series_choices_payload(raw_choices, self.series_name, suggested_name)
