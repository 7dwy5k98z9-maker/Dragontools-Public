# -*- coding: utf-8 -*-
from __future__ import annotations

from ..core.settings import (
    DEFAULT_METADATA_CACHE_DAYS,
    DEFAULT_METADATA_CACHE_ENABLED,
    DEFAULT_METADATA_FALLBACK_LANGUAGE,
    DEFAULT_METADATA_LANGUAGE,
    DEFAULT_METADATA_MOVIE_PROVIDER,
    DEFAULT_METADATA_MOVIE_PREFERRED_PROVIDER,
    DEFAULT_METADATA_SERIES_PROVIDER,
    DEFAULT_METADATA_SERIES_PREFERRED_PROVIDER,
)
from .online_metadata_settings_state import (
    OnlineMetadataSettingsState,
    load_online_metadata_settings,
    save_online_metadata_settings,
)


class OnlineMetadataDialogStateMixin:
    """Maps persistent metadata settings to and from dialog controls."""

    @staticmethod
    def _set_combo_value(combo, value: str) -> None:
        idx = combo.findText(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        else:
            combo.setEditText(value)

    @staticmethod
    def _set_combo_data(combo, value: str) -> None:
        for idx in range(combo.count()):
            if str(combo.itemData(idx)) == str(value):
                combo.setCurrentIndex(idx)
                return
        combo.setCurrentIndex(0)

    def _apply_state(self, state: OnlineMetadataSettingsState) -> None:
        self._set_combo_data(self.movie_provider_combo, state.movie_provider)
        self._set_combo_data(self.series_provider_combo, state.series_provider)
        self._set_combo_data(self.movie_preferred_combo, state.movie_preferred_provider)
        self._set_combo_data(self.series_preferred_combo, state.series_preferred_provider)
        self._update_provider_preference_state()
        self.tmdb_enabled_cb.setChecked(state.tmdb_enabled)
        self.tmdb_read_token_edit.setText(state.tmdb_read_token)
        self.tmdb_api_key_edit.setText(state.tmdb_api_key)
        self.tvdb_enabled_cb.setChecked(state.tvdb_enabled)
        self.tvdb_api_key_edit.setText(state.tvdb_api_key)
        self.tvdb_pin_edit.setText(state.tvdb_pin)
        self.tvdb_token_edit.setText(state.tvdb_bearer_token)
        self._set_combo_value(self.language_combo, state.language)
        self._set_combo_value(self.fallback_language_combo, state.fallback_language)
        self.cache_enabled_cb.setChecked(state.cache_enabled)
        self.cache_days_spin.setValue(int(state.cache_days))

    def _state_from_controls(self) -> OnlineMetadataSettingsState:
        return OnlineMetadataSettingsState(
            movie_provider=self.movie_provider_combo.currentData() or DEFAULT_METADATA_MOVIE_PROVIDER,
            series_provider=self.series_provider_combo.currentData() or DEFAULT_METADATA_SERIES_PROVIDER,
            movie_preferred_provider=(
                self.movie_preferred_combo.currentData() or DEFAULT_METADATA_MOVIE_PREFERRED_PROVIDER
            ),
            series_preferred_provider=(
                self.series_preferred_combo.currentData() or DEFAULT_METADATA_SERIES_PREFERRED_PROVIDER
            ),
            tmdb_enabled=self.tmdb_enabled_cb.isChecked(),
            tmdb_read_token=self.tmdb_read_token_edit.text().strip(),
            tmdb_api_key=self.tmdb_api_key_edit.text().strip(),
            tvdb_enabled=self.tvdb_enabled_cb.isChecked(),
            tvdb_api_key=self.tvdb_api_key_edit.text().strip(),
            tvdb_pin=self.tvdb_pin_edit.text().strip(),
            tvdb_bearer_token=self.tvdb_token_edit.text().strip(),
            language=self.language_combo.currentText().strip() or DEFAULT_METADATA_LANGUAGE,
            fallback_language=(
                self.fallback_language_combo.currentText().strip() or DEFAULT_METADATA_FALLBACK_LANGUAGE
            ),
            cache_enabled=self.cache_enabled_cb.isChecked(),
            cache_days=self.cache_days_spin.value(),
        )

    def _load(self) -> None:
        self._apply_state(load_online_metadata_settings(self.settings))

    def _reset_defaults(self) -> None:
        self._apply_state(
            OnlineMetadataSettingsState(
                movie_provider=DEFAULT_METADATA_MOVIE_PROVIDER,
                series_provider=DEFAULT_METADATA_SERIES_PROVIDER,
                movie_preferred_provider=DEFAULT_METADATA_MOVIE_PREFERRED_PROVIDER,
                series_preferred_provider=DEFAULT_METADATA_SERIES_PREFERRED_PROVIDER,
                language=DEFAULT_METADATA_LANGUAGE,
                fallback_language=DEFAULT_METADATA_FALLBACK_LANGUAGE,
                cache_enabled=DEFAULT_METADATA_CACHE_ENABLED,
                cache_days=DEFAULT_METADATA_CACHE_DAYS,
            )
        )

    def _save(self) -> None:
        save_online_metadata_settings(self.settings, self._state_from_controls())
        self.accept()
