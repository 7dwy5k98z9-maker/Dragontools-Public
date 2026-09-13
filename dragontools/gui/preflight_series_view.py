# -*- coding: utf-8 -*-
"""UI-Aufbau und direkte Benutzerinteraktionen des Serien-Preflight-Widgets."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from ..core.paths import user_path_name
from .preflight_series_choices import hide_series_folder_choices, install_series_folder_choice
from .preflight_widget_common import _fmt_path


class SeriesWidgetViewMixin:
    """Baut die Oberfläche und reagiert auf direkte Eingaben des Benutzers."""

    def _build(self, series_name: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        count = len(self.entries)
        seasons = sorted(
            {
                entry["season"]
                for entry in self.entries
                if entry.get("season") is not None
            }
        )
        season_text = ", ".join(f"{season:02d}" for season in seasons) if seasons else "?"

        episode_label = QLabel(
            f"📺  <b>{series_name}</b>"
            f"  <span style='color:#64748b;'>"
            f"({count} Folge{'n' if count != 1 else ''}, Staffeln: {season_text})"
            f"</span>"
        )
        episode_label.setTextFormat(Qt.TextFormat.RichText)
        episode_label.setWordWrap(True)
        layout.addWidget(episode_label)

        shown = self.entries[:3]
        for entry in shown:
            label = QLabel(f"  · {user_path_name(entry['path'])}")
            label.setStyleSheet("color:#64748b; font-size:11px;")
            label.setWordWrap(True)
            layout.addWidget(label)

        remaining = len(self.entries) - len(shown)
        if remaining > 0:
            more = QLabel(
                f"  · … und {remaining} weitere Datei{'en' if remaining != 1 else ''}"
            )
            more.setStyleSheet("color:#94a3b8; font-size:11px;")
            layout.addWidget(more)

        release_warnings: list[str] = []
        for entry in self.entries:
            release_warnings.extend(list(entry.get("release_warnings") or ()))
        release_warnings = list(dict.fromkeys(release_warnings))
        if release_warnings:
            warning = QLabel(
                "  ⚠️ Nicht normalisierter/Release-Dateiname erkannt: "
                + "; ".join(release_warnings)
                + ". Die Metadatensuche läuft automatisch; bei falscher Serie kann die Suche manuell überschrieben werden."
            )
            warning.setWordWrap(True)
            warning.setStyleSheet("color:#b45309; font-size:11px;")
            layout.addWidget(warning)

        row = QHBoxLayout()
        row.addWidget(QLabel("Typ:"))

        self._type_combo = QComboBox()
        self._options: list[tuple[str, str]] = []
        if self.tv_path:
            self._type_combo.addItem("📺 TV")
            self._options.append(("TV", self.tv_path))
        if self.anime_path:
            self._type_combo.addItem("🎌 Anime")
            self._options.append(("Anime", self.anime_path))

        default_index = next(
            (
                index
                for index, (type_name, _base) in enumerate(self._options)
                if type_name.lower() == self._default_type.lower()
            ),
            0,
        )
        self._type_combo.setCurrentIndex(default_index)
        self._type_combo.setMinimumWidth(120)
        self._type_combo.currentIndexChanged.connect(self._update_preview)
        row.addWidget(self._type_combo)

        row.addWidget(QLabel("Serie:"))
        self._series_edit = QLineEdit(series_name)
        self._series_edit.textChanged.connect(self._series_text_changed)
        row.addWidget(self._series_edit, 1)

        self._manual_search_btn = QPushButton("🔍 Eigene Seriensuche")
        self._manual_search_btn.clicked.connect(self._manual_series_search)
        row.addWidget(self._manual_search_btn)
        layout.addLayout(row)

        self._preview = QLabel()
        self._preview.setWordWrap(True)
        layout.addWidget(self._preview)
        self._update_preview()

        self._metadata_hint = QLabel()
        self._metadata_hint.setWordWrap(True)
        self._metadata_hint.setStyleSheet("color:#2563eb; font-size:11px;")
        self._metadata_hint.setVisible(False)
        layout.addWidget(self._metadata_hint)

        install_series_folder_choice(self, layout)

    def _manual_series_search(self) -> None:
        current = self._series_edit.text().strip()
        query, ok = QInputDialog.getText(
            self,
            "Eigene Seriensuche",
            "Serien-Suchbegriff:",
            text=current,
        )
        query = str(query or "").strip()
        if not ok or not query:
            return

        self._resolved_series_key = None
        self._resolved_series_dir = None
        self._metadata_original_name = query
        if self.__dict__.get("_folder_choice_combo") is not None:
            hide_series_folder_choices(self)
        self._series_edit.setText(query)
        if callable(self._metadata_refresh_callback):
            self._metadata_refresh_callback(self)

    def _update_preview(self) -> None:
        target = self._preview_target_dir()
        if target:
            self._preview.setText(f"  ℹ️ {_fmt_path(target)}")
            self._preview.setStyleSheet("color:#059669; font-size:11px;")
            return
        self._preview.setText("  ⚠️ Kein Zielpfad – wird nicht verschoben")
        self._preview.setStyleSheet("color:#dc2626; font-size:11px;")

    def _series_text_changed(self) -> None:
        combo = self.__dict__.get("_folder_choice_combo")
        if combo is not None and combo.isVisible():
            hide_series_folder_choices(self)
            self._resolved_series_key = None
            self._resolved_series_dir = None
        self._update_preview()
