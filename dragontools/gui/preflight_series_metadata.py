# -*- coding: utf-8 -*-
"""Metadatenjob und Ergebnisanwendung für Serien im Move-Preflight."""
from __future__ import annotations

from typing import Any

from .preflight_series_choices import hide_series_folder_choices, show_series_folder_choices
from .preflight_widget_common import _fmt_path


class SeriesWidgetMetadataMixin:
    """Kapselt Metadatenstatus und die Anwendung asynchroner Lookup-Ergebnisse."""

    def set_metadata_refresh_callback(self, callback) -> None:
        self._metadata_refresh_callback = callback

    def metadata_lookup_job(self) -> tuple[str, str, Any] | None:
        base = self._current_base_path()
        series_name = self._series_edit.text().strip()
        if not base or not series_name:
            return None
        key = f"{id(self)}:{base}:{series_name}"
        return (
            "series",
            key,
            {
                "base": base,
                "series_name": series_name,
                "search_bases": self._ordered_search_bases(),
                "year": self._single_entry_year(),
            },
        )

    def mark_metadata_lookup_started(self, online_lookup: bool = True) -> None:
        if online_lookup:
            text = "  🌐 Suche: bestehende Serienordner und Online-Serienjahr werden geladen …"
        else:
            text = "  ℹ️ Bestehende Serienordner werden im Hintergrund gesucht …"
        self._metadata_hint.setText(text)
        self._metadata_hint.setVisible(True)

    def mark_metadata_lookup_failed(self, message: str = "") -> None:
        detail = f" – {message}" if message else ""
        self._metadata_hint.setText(
            f"  🌐 Online-Metadaten: Serienjahr konnte nicht geladen werden{detail}"
        )
        self._metadata_hint.setVisible(True)

    def mark_existing_series_dir_not_found(self) -> None:
        warning = self.__dict__.get("_library_path_warning", "")
        suffix = f"\n  ⚠️ {warning}" if warning else ""
        self._metadata_hint.setText(
            f"  ℹ️ Kein bestehender Serienordner gefunden – Ziel wird neu angelegt.{suffix}"
        )
        self._metadata_hint.setVisible(True)

    def mark_library_path_warning(self, message: str) -> None:
        detail = str(message or "").strip()
        if not detail:
            return
        self._library_path_warning = detail
        self._metadata_hint.setText(f"  ⚠️ Mediathek-Datenbank: {detail}")
        self._metadata_hint.setStyleSheet("color:#b45309; font-size:11px;")
        self._metadata_hint.setVisible(True)

    def apply_unusable_library_series_match(
        self,
        *,
        message: str,
        series_name: str,
        suggested_series_name: str = "",
        base: str = "",
        base_type: str = "",
    ) -> None:
        if self._series_edit.text().strip() != series_name:
            return
        if base:
            self._select_base_path(base)
        elif base_type:
            self._select_type_name(base_type)

        suggestion = str(suggested_series_name or "").strip()
        if suggestion and self._series_edit.text().strip() == series_name:
            self._series_edit.setText(suggestion)
            self._library_name_applied = True

        self.mark_library_path_warning(message)
        self._update_preview()

    def apply_existing_series_dir(
        self,
        existing_dir: str,
        base: str,
        series_name: str,
        base_type: str = "",
        source: str = "folder_search",
        notice: str = "",
    ) -> None:
        if self._series_edit.text().strip() != series_name:
            return
        if not self._select_base_path(base):
            return
        if self.__dict__.get("_folder_choice_combo") is not None:
            hide_series_folder_choices(self)

        self._resolved_series_key = (base, series_name)
        self._resolved_series_dir = existing_dir
        type_hint = f" ({base_type})" if base_type else ""
        source_key = str(source or "").casefold()
        if source_key in {"database", "mediathek-db", "mediathek_datenbank"}:
            source_text = "🗄 Zielquelle: Mediathek-Datenbank"
        else:
            source_text = "📁 Zielquelle: Ordnersuche"

        notice_text = str(notice or "").strip()
        warning_text = str(self.__dict__.get("_library_path_warning", "") or "").strip()
        if notice_text:
            note = f"\n  ℹ️ {notice_text}"
        elif warning_text:
            note = f"\n  ⚠️ {warning_text}"
        else:
            note = ""
        self._metadata_hint.setText(
            f"  {source_text}{type_hint} – {_fmt_path(existing_dir)}{note}"
        )
        self._metadata_hint.setVisible(True)
        self._update_preview()

    def apply_existing_series_dir_choices(
        self,
        *,
        choices: list[dict],
        series_name: str,
        suggested_series_name: str = "",
    ) -> None:
        show_series_folder_choices(
            self,
            choices=choices,
            series_name=series_name,
            suggested_series_name=suggested_series_name,
        )

    def apply_online_metadata_suggestion(self, suggestion) -> None:
        warning = self.__dict__.get("_library_path_warning", "")
        suffix = f"\n  ⚠️ {warning}" if warning else ""
        if suggestion is None or not getattr(suggestion, "first_air_year", None):
            self._metadata_hint.setText(
                f"  🌐 Online-Metadaten: kein passender Serientreffer{suffix}"
            )
            self._metadata_hint.setVisible(True)
            return

        if self._series_edit.text().strip() != self._metadata_original_name:
            if self.__dict__.get("_library_name_applied", False):
                message = (
                    "  🌐 Online-Metadaten: Vorschlag nicht übernommen – "
                    "Mediathek-Serienname hat Vorrang."
                )
            else:
                message = (
                    "  🌐 Online-Metadaten: Vorschlag nicht übernommen – "
                    "Feld wurde manuell geändert."
                )
            self._metadata_hint.setText(f"{message}{suffix}")
            self._metadata_hint.setVisible(True)
            return

        self._series_edit.setText(suggestion.folder_name)
        provider = (
            "TheTVDB"
            if str(getattr(suggestion, "provider", "") or "").casefold() == "thetvdb"
            else "TMDB"
        )
        self._metadata_hint.setText(
            f"  🌐 Zielquelle: {provider} – Serienjahr vorgeschlagen: "
            f"{suggestion.folder_name}{suffix}"
        )
        self._metadata_hint.setVisible(True)
        self._update_preview()
