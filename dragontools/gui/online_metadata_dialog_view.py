# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)


class OnlineMetadataDialogViewMixin:
    """Builds the online metadata settings dialog and owns presentation state."""

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        intro = QLabel(
            "Online-Metadaten sind optional. Dragon Tools nutzt sie später für "
            "Filmreihen, Serienjahre, Episodentitel, NFOs und bessere Umbenennungs-Vorschläge."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        layout.addWidget(self._build_provider_group())
        layout.addWidget(self._build_tmdb_group())
        layout.addWidget(self._build_tvdb_group())
        layout.addWidget(self._build_secrets_group())
        layout.addWidget(self._build_options_group())
        layout.addLayout(self._build_button_row())

    def _build_provider_group(self) -> QGroupBox:
        group = QGroupBox("Quellen")
        grid = QGridLayout(group)
        self.movie_provider_combo = self._provider_combo(include_both=True)
        self.movie_preferred_combo = self._provider_combo(include_both=False)
        self.series_provider_combo = self._provider_combo(include_both=True)
        self.series_preferred_combo = self._provider_combo(include_both=False)

        grid.addWidget(QLabel("Filme:"), 0, 0)
        grid.addWidget(self.movie_provider_combo, 0, 1)
        grid.addWidget(QLabel("Bevorzugt:"), 0, 2)
        grid.addWidget(self.movie_preferred_combo, 0, 3)
        grid.addWidget(QLabel("Serien:"), 1, 0)
        grid.addWidget(self.series_provider_combo, 1, 1)
        grid.addWidget(QLabel("Bevorzugt:"), 1, 2)
        grid.addWidget(self.series_preferred_combo, 1, 3)

        hint = QLabel(
            "Filme und Serien wählen getrennt, welche aktivierte Metadatenquelle verwendet wird. "
            "Bei Beide bestimmt 'Bevorzugt', welcher Dienst zuerst verwendet wird; "
            "der andere dient als Fallback und bleibt in der Trefferauswahl verfügbar."
        )
        hint.setWordWrap(True)
        grid.addWidget(hint, 2, 0, 1, 4)
        self.movie_provider_combo.currentIndexChanged.connect(self._update_provider_preference_state)
        self.series_provider_combo.currentIndexChanged.connect(self._update_provider_preference_state)
        return group

    @staticmethod
    def _provider_combo(*, include_both: bool) -> QComboBox:
        combo = QComboBox()
        combo.addItem("TMDB", "tmdb")
        combo.addItem("TheTVDB", "thetvdb")
        if include_both:
            combo.addItem("Beide", "both")
        return combo

    def _build_tmdb_group(self) -> QGroupBox:
        group = QGroupBox("TMDB")
        grid = QGridLayout(group)
        self.tmdb_enabled_cb = QCheckBox("TMDB verwenden")
        self.tmdb_read_token_edit = self._secret_edit("API Read Access Token")
        self.tmdb_api_key_edit = self._secret_edit("API Key / v3-Key")
        grid.addWidget(self.tmdb_enabled_cb, 0, 0, 1, 3)
        grid.addWidget(QLabel("Read-Access-Token:"), 1, 0)
        grid.addWidget(self.tmdb_read_token_edit, 1, 1, 1, 2)
        grid.addWidget(QLabel("API-Key:"), 2, 0)
        grid.addWidget(self.tmdb_api_key_edit, 2, 1, 1, 2)
        hint = QLabel(
            "Empfohlen ist der Read-Access-Token. Der API-Key bleibt als "
            "Fallback hinterlegt, falls später ein Providerpfad ihn benötigt."
        )
        hint.setWordWrap(True)
        grid.addWidget(hint, 3, 0, 1, 3)
        return group

    def _build_tvdb_group(self) -> QGroupBox:
        group = QGroupBox("TheTVDB")
        grid = QGridLayout(group)
        self.tvdb_enabled_cb = QCheckBox("TheTVDB verwenden")
        self.tvdb_api_key_edit = self._secret_edit("TheTVDB API-Key")
        self.tvdb_pin_edit = self._secret_edit("Subscriber PIN, falls vorhanden")
        self.tvdb_token_edit = self._secret_edit("Optional: vorhandenes Bearer-Token")
        grid.addWidget(self.tvdb_enabled_cb, 0, 0, 1, 3)
        grid.addWidget(QLabel("API-Key:"), 1, 0)
        grid.addWidget(self.tvdb_api_key_edit, 1, 1, 1, 2)
        grid.addWidget(QLabel("PIN:"), 2, 0)
        grid.addWidget(self.tvdb_pin_edit, 2, 1, 1, 2)
        grid.addWidget(QLabel("Bearer-Token:"), 3, 0)
        grid.addWidget(self.tvdb_token_edit, 3, 1, 1, 2)
        hint = QLabel(
            "Dragon Tools erzeugt bei Bedarf automatisch ein temporäres Bearer-Token aus API-Key und PIN. "
            "Ein manuell eingetragenes Bearer-Token wird direkt verwendet."
        )
        hint.setWordWrap(True)
        grid.addWidget(hint, 4, 0, 1, 3)
        return group

    def _build_secrets_group(self) -> QGroupBox:
        group = QGroupBox("Zugangsdaten")
        layout = QHBoxLayout(group)
        self.show_secrets_cb = QCheckBox("Zugangsdaten anzeigen (TMDB + TheTVDB)")
        self.show_secrets_cb.toggled.connect(self._toggle_secret_visibility)
        layout.addWidget(self.show_secrets_cb)
        layout.addStretch(1)
        return group

    def _build_options_group(self) -> QGroupBox:
        group = QGroupBox("Sprache und Cache")
        grid = QGridLayout(group)
        self.language_combo = self._language_combo(("de-DE", "en-US", "ja-JP", "fr-FR"))
        self.fallback_language_combo = self._language_combo(("en-US", "de-DE", "ja-JP", "fr-FR"))
        self.cache_enabled_cb = QCheckBox("Metadaten-Cache verwenden")
        self.cache_days_spin = QSpinBox()
        self.cache_days_spin.setRange(1, 365)
        self.cache_days_spin.setSuffix(" Tage")
        grid.addWidget(QLabel("Sprache:"), 0, 0)
        grid.addWidget(self.language_combo, 0, 1)
        grid.addWidget(QLabel("Fallback-Sprache:"), 1, 0)
        grid.addWidget(self.fallback_language_combo, 1, 1)
        grid.addWidget(self.cache_enabled_cb, 2, 0, 1, 2)
        grid.addWidget(QLabel("Cache erneuern nach:"), 3, 0)
        grid.addWidget(self.cache_days_spin, 3, 1)
        return group

    def _build_button_row(self) -> QHBoxLayout:
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        if save_button is not None:
            save_button.setText("Speichern")
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_button is not None:
            cancel_button.setText("Abbrechen")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        row = QHBoxLayout()
        reset_button = QPushButton("Standard")
        reset_button.clicked.connect(self._reset_defaults)
        row.addWidget(reset_button)
        row.addStretch(1)
        row.addWidget(buttons)
        return row

    @staticmethod
    def _secret_edit(placeholder: str) -> QLineEdit:
        edit = QLineEdit()
        edit.setEchoMode(QLineEdit.EchoMode.Password)
        edit.setPlaceholderText(placeholder)
        return edit

    @staticmethod
    def _language_combo(values: tuple[str, ...]) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)
        combo.addItems(values)
        return combo

    def _update_provider_preference_state(self) -> None:
        self.movie_preferred_combo.setEnabled(self.movie_provider_combo.currentData() == "both")
        self.series_preferred_combo.setEnabled(self.series_provider_combo.currentData() == "both")

    def _toggle_secret_visibility(self, visible: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        for edit in (
            self.tmdb_read_token_edit,
            self.tmdb_api_key_edit,
            self.tvdb_api_key_edit,
            self.tvdb_pin_edit,
            self.tvdb_token_edit,
        ):
            edit.setEchoMode(mode)
