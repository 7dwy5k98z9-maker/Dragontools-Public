# -*- coding: utf-8 -*-
"""Orchestrates DB, folder and online resolution for series preflight metadata."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .preflight_metadata_common import (
    existing_series_payload,
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
        # Ohne bekannte Edition zuerst alle lokalen Kandidaten sammeln. Weder
        # ein exakter DB-Treffer noch ein Online-Vorschlag darf alternative
        # Jahrgaenge/Schreibvarianten aus dem Auswahl-Dropdown verdraengen.
        raw_choices = [] if self.desired_year else self.folders.choices(self.series_name, None)
        if len(raw_choices) > 1:
            return series_choices_payload(raw_choices, self.series_name)

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

        by_year = self._resolve_folders_for_known_year()
        if by_year is not None:
            return by_year

        # A known edition/year is authoritative. A year-less retry would
        # select e.g. the 1989 series after the requested 2024 lookup failed.
        local = self._resolve_raw_folder_choices(raw_choices)
        if local is not None:
            return local

        if self.online_enabled:
            suggestion = self.online.lookup(self.desired_year)
            if suggestion is not None and library_warning is not None:
                result = dict(library_warning)
                result["__online_series_suggestion__"] = suggestion
                return result
            return suggestion or library_warning
        return library_warning or {"__local_series_missing__": True}

    def _resolve_folders_for_known_year(self):
        if not self.desired_year:
            return None
        choices = self.folders.choices(self.series_name, self.desired_year)
        if len(choices) == 1:
            return existing_series_payload(choices[0], self.series_name)
        if len(choices) > 1:
            return series_choices_payload(choices, self.series_name)
        return None

    def _resolve_raw_folder_choices(self, raw_choices: list):
        if len(raw_choices) == 1:
            return existing_series_payload(raw_choices[0], self.series_name)
        if len(raw_choices) <= 1:
            return None
        return series_choices_payload(raw_choices, self.series_name)
