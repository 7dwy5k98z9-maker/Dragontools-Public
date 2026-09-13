# -*- coding: utf-8 -*-
"""Seriengruppen-Widget des Move-Preflights."""
from __future__ import annotations

from PyQt6.QtWidgets import QComboBox, QWidget

from .preflight_series_metadata import SeriesWidgetMetadataMixin
from .preflight_series_paths import SeriesWidgetPathMixin
from .preflight_series_view import SeriesWidgetViewMixin


class SeriesGroupWidget(
    SeriesWidgetMetadataMixin,
    SeriesWidgetPathMixin,
    SeriesWidgetViewMixin,
    QWidget,
):
    """Schmale Widget-Fassade; Fachbereiche liegen in den drei Mixins."""

    def __init__(
        self,
        series_name: str,
        entries: list[dict],
        tv_path: str | None,
        anime_path: str | None,
        default_type: str = "Anime",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.entries = entries
        self.tv_path = tv_path
        self.anime_path = anime_path
        self._default_type = default_type
        self._metadata_original_name = series_name
        self._resolved_series_key: tuple[str, str] | None = None
        self._resolved_series_dir: str | None = None
        self._library_path_warning = ""
        self._library_name_applied = False
        self._folder_choice_combo: QComboBox | None = None
        self._metadata_refresh_callback = None
        self._build(series_name)
