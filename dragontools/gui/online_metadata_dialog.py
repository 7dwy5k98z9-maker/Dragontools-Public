# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..core.settings import (
    APP_NAME,
    APP_ORG,
    APP_VERSION,
    DEFAULT_METADATA_CACHE_DAYS,
    DEFAULT_METADATA_CACHE_ENABLED,
    DEFAULT_METADATA_FALLBACK_LANGUAGE,
    DEFAULT_METADATA_LANGUAGE,
    DEFAULT_METADATA_MOVIE_PROVIDER,
    DEFAULT_METADATA_SERIES_PROVIDER,
    DEFAULT_METADATA_MOVIE_PREFERRED_PROVIDER,
    DEFAULT_METADATA_SERIES_PREFERRED_PROVIDER,
    SET_KEY_METADATA_CACHE_DAYS,
    SET_KEY_METADATA_CACHE_ENABLED,
    SET_KEY_METADATA_FALLBACK_LANGUAGE,
    SET_KEY_METADATA_LANGUAGE,
    SET_KEY_METADATA_MOVIE_PROVIDER,
    SET_KEY_METADATA_SERIES_PROVIDER,
    SET_KEY_METADATA_MOVIE_PREFERRED_PROVIDER,
    SET_KEY_METADATA_SERIES_PREFERRED_PROVIDER,
    SET_KEY_METADATA_TMDB_API_KEY,
    SET_KEY_METADATA_TMDB_ENABLED,
    SET_KEY_METADATA_TMDB_READ_TOKEN,
    SET_KEY_METADATA_TVDB_API_KEY,
    SET_KEY_METADATA_TVDB_BEARER_TOKEN,
    SET_KEY_METADATA_TVDB_ENABLED,
    SET_KEY_METADATA_TVDB_PIN,
)
from .ui_helpers import install_persistent_window_geometry


class OnlineMetadataDialog(QDialog):
    """Einstellungen für optionale Online-Metadatenquellen."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Online-Metadaten – Dragon Tools V{APP_VERSION}")
        self.setMinimumWidth(640)
        self.settings = QSettings(APP_ORG, APP_NAME)
        self._init_ui()
        self._load()
        install_persistent_window_geometry(self, "online_metadata_dialog", self.settings)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        intro = QLabel(
            "Online-Metadaten sind optional. Dragon Tools nutzt sie später für "
            "Filmreihen, Serienjahre, Episodentitel, NFOs und bessere Umbenennungs-Vorschläge."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        provider_group = QGroupBox("Quellen")
        provider_grid = QGridLayout(provider_group)

        self.movie_provider_combo = QComboBox()
        self.movie_provider_combo.addItem("TMDB", "tmdb")
        self.movie_provider_combo.addItem("TheTVDB", "thetvdb")
        self.movie_provider_combo.addItem("Beide", "both")
        self.movie_preferred_combo = QComboBox()
        self.movie_preferred_combo.addItem("TMDB", "tmdb")
        self.movie_preferred_combo.addItem("TheTVDB", "thetvdb")
        provider_grid.addWidget(QLabel("Filme:"), 0, 0)
        provider_grid.addWidget(self.movie_provider_combo, 0, 1)
        provider_grid.addWidget(QLabel("Bevorzugt:"), 0, 2)
        provider_grid.addWidget(self.movie_preferred_combo, 0, 3)

        self.series_provider_combo = QComboBox()
        self.series_provider_combo.addItem("TMDB", "tmdb")
        self.series_provider_combo.addItem("TheTVDB", "thetvdb")
        self.series_provider_combo.addItem("Beide", "both")
        self.series_preferred_combo = QComboBox()
        self.series_preferred_combo.addItem("TMDB", "tmdb")
        self.series_preferred_combo.addItem("TheTVDB", "thetvdb")
        provider_grid.addWidget(QLabel("Serien:"), 1, 0)
        provider_grid.addWidget(self.series_provider_combo, 1, 1)
        provider_grid.addWidget(QLabel("Bevorzugt:"), 1, 2)
        provider_grid.addWidget(self.series_preferred_combo, 1, 3)

        provider_hint = QLabel(
            "Filme und Serien wählen getrennt, welche aktivierte Metadatenquelle verwendet wird. "
            "Bei Beide bestimmt 'Bevorzugt', welcher Dienst zuerst verwendet wird; "
            "der andere dient als Fallback und bleibt in der Trefferauswahl verfügbar."
        )
        provider_hint.setWordWrap(True)
        provider_grid.addWidget(provider_hint, 2, 0, 1, 4)
        self.movie_provider_combo.currentIndexChanged.connect(self._update_provider_preference_state)
        self.series_provider_combo.currentIndexChanged.connect(self._update_provider_preference_state)
        layout.addWidget(provider_group)

        tmdb_group = QGroupBox("TMDB")
        grid = QGridLayout(tmdb_group)

        self.tmdb_enabled_cb = QCheckBox("TMDB verwenden")
        grid.addWidget(self.tmdb_enabled_cb, 0, 0, 1, 3)

        self.tmdb_read_token_edit = QLineEdit()
        self.tmdb_read_token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.tmdb_read_token_edit.setPlaceholderText("API Read Access Token")
        grid.addWidget(QLabel("Read-Access-Token:"), 1, 0)
        grid.addWidget(self.tmdb_read_token_edit, 1, 1, 1, 2)

        self.tmdb_api_key_edit = QLineEdit()
        self.tmdb_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.tmdb_api_key_edit.setPlaceholderText("API Key / v3-Key")
        grid.addWidget(QLabel("API-Key:"), 2, 0)
        grid.addWidget(self.tmdb_api_key_edit, 2, 1, 1, 2)

        hint = QLabel(
            "Empfohlen ist der Read-Access-Token. Der API-Key bleibt als "
            "Fallback hinterlegt, falls später ein Providerpfad ihn benötigt."
        )
        hint.setWordWrap(True)
        grid.addWidget(hint, 3, 0, 1, 3)
        layout.addWidget(tmdb_group)

        tvdb_group = QGroupBox("TheTVDB")
        tvdb_grid = QGridLayout(tvdb_group)

        self.tvdb_enabled_cb = QCheckBox("TheTVDB verwenden")
        tvdb_grid.addWidget(self.tvdb_enabled_cb, 0, 0, 1, 3)

        self.tvdb_api_key_edit = QLineEdit()
        self.tvdb_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.tvdb_api_key_edit.setPlaceholderText("TheTVDB API-Key")
        tvdb_grid.addWidget(QLabel("API-Key:"), 1, 0)
        tvdb_grid.addWidget(self.tvdb_api_key_edit, 1, 1, 1, 2)

        self.tvdb_pin_edit = QLineEdit()
        self.tvdb_pin_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.tvdb_pin_edit.setPlaceholderText("Subscriber PIN, falls vorhanden")
        tvdb_grid.addWidget(QLabel("PIN:"), 2, 0)
        tvdb_grid.addWidget(self.tvdb_pin_edit, 2, 1, 1, 2)

        self.tvdb_token_edit = QLineEdit()
        self.tvdb_token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.tvdb_token_edit.setPlaceholderText("Optional: vorhandenes Bearer-Token")
        tvdb_grid.addWidget(QLabel("Bearer-Token:"), 3, 0)
        tvdb_grid.addWidget(self.tvdb_token_edit, 3, 1, 1, 2)

        tvdb_hint = QLabel(
            "Dragon Tools erzeugt bei Bedarf automatisch ein temporäres Bearer-Token aus API-Key und PIN. "
            "Ein manuell eingetragenes Bearer-Token wird direkt verwendet."
        )
        tvdb_hint.setWordWrap(True)
        tvdb_grid.addWidget(tvdb_hint, 4, 0, 1, 3)
        layout.addWidget(tvdb_group)

        secrets_group = QGroupBox("Zugangsdaten")
        secrets_layout = QHBoxLayout(secrets_group)
        self.show_secrets_cb = QCheckBox("Zugangsdaten anzeigen (TMDB + TheTVDB)")
        self.show_secrets_cb.toggled.connect(self._toggle_secret_visibility)
        secrets_layout.addWidget(self.show_secrets_cb)
        secrets_layout.addStretch(1)
        layout.addWidget(secrets_group)

        options_group = QGroupBox("Sprache und Cache")
        options = QGridLayout(options_group)

        self.language_combo = QComboBox()
        self.language_combo.setEditable(True)
        self.language_combo.addItems(["de-DE", "en-US", "ja-JP", "fr-FR"])
        options.addWidget(QLabel("Sprache:"), 0, 0)
        options.addWidget(self.language_combo, 0, 1)

        self.fallback_language_combo = QComboBox()
        self.fallback_language_combo.setEditable(True)
        self.fallback_language_combo.addItems(["en-US", "de-DE", "ja-JP", "fr-FR"])
        options.addWidget(QLabel("Fallback-Sprache:"), 1, 0)
        options.addWidget(self.fallback_language_combo, 1, 1)

        self.cache_enabled_cb = QCheckBox("Metadaten-Cache verwenden")
        options.addWidget(self.cache_enabled_cb, 2, 0, 1, 2)

        self.cache_days_spin = QSpinBox()
        self.cache_days_spin.setRange(1, 365)
        self.cache_days_spin.setSuffix(" Tage")
        options.addWidget(QLabel("Cache erneuern nach:"), 3, 0)
        options.addWidget(self.cache_days_spin, 3, 1)

        layout.addWidget(options_group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        if save_button is not None:
            save_button.setText("Speichern")
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_button is not None:
            cancel_button.setText("Abbrechen")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        bottom = QHBoxLayout()
        reset_button = QPushButton("Standard")
        reset_button.clicked.connect(self._reset_defaults)
        bottom.addWidget(reset_button)
        bottom.addStretch(1)
        bottom.addWidget(buttons)
        layout.addLayout(bottom)

    def _update_provider_preference_state(self) -> None:
        self.movie_preferred_combo.setEnabled(self.movie_provider_combo.currentData() == "both")
        self.series_preferred_combo.setEnabled(self.series_provider_combo.currentData() == "both")

    def _toggle_secret_visibility(self, visible: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        self.tmdb_read_token_edit.setEchoMode(mode)
        self.tmdb_api_key_edit.setEchoMode(mode)
        self.tvdb_api_key_edit.setEchoMode(mode)
        self.tvdb_pin_edit.setEchoMode(mode)
        self.tvdb_token_edit.setEchoMode(mode)

    def _set_combo_value(self, combo: QComboBox, value: str) -> None:
        idx = combo.findText(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        else:
            combo.setEditText(value)

    def _set_combo_data(self, combo: QComboBox, value: str) -> None:
        for idx in range(combo.count()):
            if str(combo.itemData(idx)) == str(value):
                combo.setCurrentIndex(idx)
                return
        combo.setCurrentIndex(0)

    def _load(self) -> None:
        s = self.settings
        self._set_combo_data(
            self.movie_provider_combo,
            s.value(SET_KEY_METADATA_MOVIE_PROVIDER, DEFAULT_METADATA_MOVIE_PROVIDER, type=str),
        )
        self._set_combo_data(
            self.series_provider_combo,
            s.value(SET_KEY_METADATA_SERIES_PROVIDER, DEFAULT_METADATA_SERIES_PROVIDER, type=str),
        )
        self._set_combo_data(
            self.movie_preferred_combo,
            s.value(
                SET_KEY_METADATA_MOVIE_PREFERRED_PROVIDER,
                DEFAULT_METADATA_MOVIE_PREFERRED_PROVIDER,
                type=str,
            ),
        )
        self._set_combo_data(
            self.series_preferred_combo,
            s.value(
                SET_KEY_METADATA_SERIES_PREFERRED_PROVIDER,
                DEFAULT_METADATA_SERIES_PREFERRED_PROVIDER,
                type=str,
            ),
        )
        self._update_provider_preference_state()
        self.tmdb_enabled_cb.setChecked(
            s.value(SET_KEY_METADATA_TMDB_ENABLED, False, type=bool)
        )
        self.tmdb_read_token_edit.setText(
            s.value(SET_KEY_METADATA_TMDB_READ_TOKEN, "", type=str)
        )
        self.tmdb_api_key_edit.setText(
            s.value(SET_KEY_METADATA_TMDB_API_KEY, "", type=str)
        )
        self.tvdb_enabled_cb.setChecked(
            s.value(SET_KEY_METADATA_TVDB_ENABLED, False, type=bool)
        )
        self.tvdb_api_key_edit.setText(
            s.value(SET_KEY_METADATA_TVDB_API_KEY, "", type=str)
        )
        self.tvdb_pin_edit.setText(
            s.value(SET_KEY_METADATA_TVDB_PIN, "", type=str)
        )
        self.tvdb_token_edit.setText(
            s.value(SET_KEY_METADATA_TVDB_BEARER_TOKEN, "", type=str)
        )
        self._set_combo_value(
            self.language_combo,
            s.value(SET_KEY_METADATA_LANGUAGE, DEFAULT_METADATA_LANGUAGE, type=str),
        )
        self._set_combo_value(
            self.fallback_language_combo,
            s.value(
                SET_KEY_METADATA_FALLBACK_LANGUAGE,
                DEFAULT_METADATA_FALLBACK_LANGUAGE,
                type=str,
            ),
        )
        self.cache_enabled_cb.setChecked(
            s.value(
                SET_KEY_METADATA_CACHE_ENABLED,
                DEFAULT_METADATA_CACHE_ENABLED,
                type=bool,
            )
        )
        self.cache_days_spin.setValue(
            int(s.value(SET_KEY_METADATA_CACHE_DAYS, DEFAULT_METADATA_CACHE_DAYS, type=int))
        )

    def _reset_defaults(self) -> None:
        self._set_combo_data(self.movie_provider_combo, DEFAULT_METADATA_MOVIE_PROVIDER)
        self._set_combo_data(self.series_provider_combo, DEFAULT_METADATA_SERIES_PROVIDER)
        self._set_combo_data(self.movie_preferred_combo, DEFAULT_METADATA_MOVIE_PREFERRED_PROVIDER)
        self._set_combo_data(self.series_preferred_combo, DEFAULT_METADATA_SERIES_PREFERRED_PROVIDER)
        self._update_provider_preference_state()
        self.tmdb_enabled_cb.setChecked(False)
        self.tmdb_read_token_edit.clear()
        self.tmdb_api_key_edit.clear()
        self.tvdb_enabled_cb.setChecked(False)
        self.tvdb_api_key_edit.clear()
        self.tvdb_pin_edit.clear()
        self.tvdb_token_edit.clear()
        self._set_combo_value(self.language_combo, DEFAULT_METADATA_LANGUAGE)
        self._set_combo_value(self.fallback_language_combo, DEFAULT_METADATA_FALLBACK_LANGUAGE)
        self.cache_enabled_cb.setChecked(DEFAULT_METADATA_CACHE_ENABLED)
        self.cache_days_spin.setValue(DEFAULT_METADATA_CACHE_DAYS)

    def _save(self) -> None:
        s = self.settings
        s.setValue(SET_KEY_METADATA_MOVIE_PROVIDER, self.movie_provider_combo.currentData() or DEFAULT_METADATA_MOVIE_PROVIDER)
        s.setValue(SET_KEY_METADATA_SERIES_PROVIDER, self.series_provider_combo.currentData() or DEFAULT_METADATA_SERIES_PROVIDER)
        s.setValue(
            SET_KEY_METADATA_MOVIE_PREFERRED_PROVIDER,
            self.movie_preferred_combo.currentData() or DEFAULT_METADATA_MOVIE_PREFERRED_PROVIDER,
        )
        s.setValue(
            SET_KEY_METADATA_SERIES_PREFERRED_PROVIDER,
            self.series_preferred_combo.currentData() or DEFAULT_METADATA_SERIES_PREFERRED_PROVIDER,
        )
        s.setValue(SET_KEY_METADATA_TMDB_ENABLED, self.tmdb_enabled_cb.isChecked())
        s.setValue(SET_KEY_METADATA_TMDB_READ_TOKEN, self.tmdb_read_token_edit.text().strip())
        s.setValue(SET_KEY_METADATA_TMDB_API_KEY, self.tmdb_api_key_edit.text().strip())
        s.setValue(SET_KEY_METADATA_TVDB_ENABLED, self.tvdb_enabled_cb.isChecked())
        s.setValue(SET_KEY_METADATA_TVDB_API_KEY, self.tvdb_api_key_edit.text().strip())
        s.setValue(SET_KEY_METADATA_TVDB_PIN, self.tvdb_pin_edit.text().strip())
        s.setValue(SET_KEY_METADATA_TVDB_BEARER_TOKEN, self.tvdb_token_edit.text().strip())
        s.setValue(SET_KEY_METADATA_LANGUAGE, self.language_combo.currentText().strip() or DEFAULT_METADATA_LANGUAGE)
        s.setValue(
            SET_KEY_METADATA_FALLBACK_LANGUAGE,
            self.fallback_language_combo.currentText().strip() or DEFAULT_METADATA_FALLBACK_LANGUAGE,
        )
        s.setValue(SET_KEY_METADATA_CACHE_ENABLED, self.cache_enabled_cb.isChecked())
        s.setValue(SET_KEY_METADATA_CACHE_DAYS, self.cache_days_spin.value())
        s.sync()
        self.accept()
