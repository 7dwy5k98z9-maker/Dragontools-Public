# -*- coding: utf-8 -*-
"""Pfad-, Bereichs- und Zielplanung für Serien im Move-Preflight."""
from __future__ import annotations

from .preflight_series_choices import (
    NO_SERIES_FOLDER_CHOICE,
    selected_series_folder_choice,
    validate_series_folder_choice,
)
from .preflight_widget_common import _base_path_key, _series_root_from_input, _series_season_target


class SeriesWidgetPathMixin:
    """Kapselt die komplette Pfad- und Zielverzeichnislogik des Widgets."""

    def _series_root_dir(self) -> str | None:
        base = self._current_base_path()
        series_name = self._series_edit.text().strip()
        if not base or not series_name:
            return None

        key = (base, series_name)
        if self._resolved_series_key == key and self._resolved_series_dir:
            return self._resolved_series_dir

        choice = selected_series_folder_choice(self, base, series_name)
        if choice is not NO_SERIES_FOLDER_CHOICE:
            return str(choice or "") or None
        return _series_root_from_input(base, series_name)

    def _current_base_path(self) -> str | None:
        if not self._options:
            return None
        index = self._type_combo.currentIndex()
        if index < 0 or index >= len(self._options):
            return None
        return self._options[index][1]

    def _ordered_search_bases(self) -> list[dict[str, str]]:
        """Aktuell gewählten Serienbereich zuerst, danach die weiteren Bereiche."""
        if not self._options:
            return []

        current_index = self._type_combo.currentIndex()
        ordered: list[tuple[str, str]] = []
        if 0 <= current_index < len(self._options):
            ordered.append(self._options[current_index])
        for option in self._options:
            if option not in ordered:
                ordered.append(option)

        seen: set[str] = set()
        result: list[dict[str, str]] = []
        for type_name, base in ordered:
            key = _base_path_key(base)
            if not key or key in seen:
                continue
            seen.add(key)
            result.append({"type": type_name, "base": base})
        return result

    def _select_base_path(self, base: str) -> bool:
        wanted = _base_path_key(base)
        if not wanted:
            return False
        for index, (_type_name, option_base) in enumerate(self._options):
            if _base_path_key(option_base) != wanted:
                continue
            setter = getattr(self._type_combo, "setCurrentIndex", None)
            if callable(setter) and self._type_combo.currentIndex() != index:
                setter(index)
            return True
        return False

    def _select_type_name(self, type_name: str) -> bool:
        wanted = str(type_name or "").strip().casefold()
        if not wanted:
            return False
        for index, (option_type, _option_base) in enumerate(self.__dict__.get("_options", [])):
            if option_type.casefold() != wanted:
                continue
            setter = getattr(self._type_combo, "setCurrentIndex", None)
            if callable(setter) and self._type_combo.currentIndex() != index:
                setter(index)
            return True
        return False

    def _single_entry_year(self) -> int | None:
        years = {
            int(entry["year"])
            for entry in self.__dict__.get("entries", [])
            if entry.get("year")
        }
        return years.pop() if len(years) == 1 else None

    def _preview_target_dir(self) -> str | None:
        base_dir = self._series_root_dir()
        if not base_dir:
            return None
        first_entry = next(
            (entry for entry in self.entries if entry.get("season") is not None),
            None,
        )
        if not first_entry:
            return None
        return _series_season_target(base_dir, first_entry["season"])

    def get_planned_targets(self) -> dict[str, str | dict]:
        base_dir = self._series_root_dir()
        if not base_dir:
            return {}

        result: dict[str, str] = {}
        for entry in self.entries:
            season = entry.get("season")
            if season is None:
                continue
            target_dir = _series_season_target(base_dir, season)
            if target_dir:
                result[entry["path"]] = target_dir
        return result

    def validate(self) -> tuple[bool, str]:
        return validate_series_folder_choice(self)
