# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..core.secret_settings import read_secret, write_secret
from ..core.settings_metadata import DEFAULT_METADATA_CACHE_DAYS, DEFAULT_METADATA_CACHE_ENABLED, DEFAULT_METADATA_FALLBACK_LANGUAGE, DEFAULT_METADATA_LANGUAGE, DEFAULT_METADATA_MOVIE_PROVIDER, DEFAULT_METADATA_MOVIE_PREFERRED_PROVIDER, DEFAULT_METADATA_SERIES_PROVIDER, DEFAULT_METADATA_SERIES_PREFERRED_PROVIDER, SET_KEY_METADATA_CACHE_DAYS, SET_KEY_METADATA_CACHE_ENABLED, SET_KEY_METADATA_FALLBACK_LANGUAGE, SET_KEY_METADATA_LANGUAGE, SET_KEY_METADATA_MOVIE_PROVIDER, SET_KEY_METADATA_MOVIE_PREFERRED_PROVIDER, SET_KEY_METADATA_SERIES_PROVIDER, SET_KEY_METADATA_SERIES_PREFERRED_PROVIDER, SET_KEY_METADATA_TMDB_API_KEY, SET_KEY_METADATA_TMDB_ENABLED, SET_KEY_METADATA_TMDB_READ_TOKEN, SET_KEY_METADATA_TVDB_API_KEY, SET_KEY_METADATA_TVDB_BEARER_TOKEN, SET_KEY_METADATA_TVDB_ENABLED, SET_KEY_METADATA_TVDB_PIN


class SettingsStore(Protocol):
    def value(self, key: str, defaultValue=None, *, type=None): ...
    def setValue(self, key: str, value) -> None: ...
    def sync(self) -> None: ...


@dataclass(frozen=True)
class OnlineMetadataSettingsState:
    movie_provider: str = DEFAULT_METADATA_MOVIE_PROVIDER
    series_provider: str = DEFAULT_METADATA_SERIES_PROVIDER
    movie_preferred_provider: str = DEFAULT_METADATA_MOVIE_PREFERRED_PROVIDER
    series_preferred_provider: str = DEFAULT_METADATA_SERIES_PREFERRED_PROVIDER
    tmdb_enabled: bool = False
    tmdb_read_token: str = ""
    tmdb_api_key: str = ""
    tvdb_enabled: bool = False
    tvdb_api_key: str = ""
    tvdb_pin: str = ""
    tvdb_bearer_token: str = ""
    language: str = DEFAULT_METADATA_LANGUAGE
    fallback_language: str = DEFAULT_METADATA_FALLBACK_LANGUAGE
    cache_enabled: bool = DEFAULT_METADATA_CACHE_ENABLED
    cache_days: int = DEFAULT_METADATA_CACHE_DAYS


def load_online_metadata_settings(settings: SettingsStore) -> OnlineMetadataSettingsState:
    return OnlineMetadataSettingsState(
        movie_provider=settings.value(
            SET_KEY_METADATA_MOVIE_PROVIDER, DEFAULT_METADATA_MOVIE_PROVIDER, type=str
        ),
        series_provider=settings.value(
            SET_KEY_METADATA_SERIES_PROVIDER, DEFAULT_METADATA_SERIES_PROVIDER, type=str
        ),
        movie_preferred_provider=settings.value(
            SET_KEY_METADATA_MOVIE_PREFERRED_PROVIDER,
            DEFAULT_METADATA_MOVIE_PREFERRED_PROVIDER,
            type=str,
        ),
        series_preferred_provider=settings.value(
            SET_KEY_METADATA_SERIES_PREFERRED_PROVIDER,
            DEFAULT_METADATA_SERIES_PREFERRED_PROVIDER,
            type=str,
        ),
        tmdb_enabled=settings.value(SET_KEY_METADATA_TMDB_ENABLED, False, type=bool),
        tmdb_read_token=read_secret(settings, SET_KEY_METADATA_TMDB_READ_TOKEN),
        tmdb_api_key=read_secret(settings, SET_KEY_METADATA_TMDB_API_KEY),
        tvdb_enabled=settings.value(SET_KEY_METADATA_TVDB_ENABLED, False, type=bool),
        tvdb_api_key=read_secret(settings, SET_KEY_METADATA_TVDB_API_KEY),
        tvdb_pin=read_secret(settings, SET_KEY_METADATA_TVDB_PIN),
        tvdb_bearer_token=read_secret(settings, SET_KEY_METADATA_TVDB_BEARER_TOKEN),
        language=settings.value(SET_KEY_METADATA_LANGUAGE, DEFAULT_METADATA_LANGUAGE, type=str),
        fallback_language=settings.value(
            SET_KEY_METADATA_FALLBACK_LANGUAGE, DEFAULT_METADATA_FALLBACK_LANGUAGE, type=str
        ),
        cache_enabled=settings.value(
            SET_KEY_METADATA_CACHE_ENABLED, DEFAULT_METADATA_CACHE_ENABLED, type=bool
        ),
        cache_days=int(
            settings.value(SET_KEY_METADATA_CACHE_DAYS, DEFAULT_METADATA_CACHE_DAYS, type=int)
        ),
    )


def save_online_metadata_settings(
    settings: SettingsStore,
    state: OnlineMetadataSettingsState,
) -> None:
    values = (
        (SET_KEY_METADATA_MOVIE_PROVIDER, state.movie_provider),
        (SET_KEY_METADATA_SERIES_PROVIDER, state.series_provider),
        (SET_KEY_METADATA_MOVIE_PREFERRED_PROVIDER, state.movie_preferred_provider),
        (SET_KEY_METADATA_SERIES_PREFERRED_PROVIDER, state.series_preferred_provider),
        (SET_KEY_METADATA_TMDB_ENABLED, state.tmdb_enabled),
        (SET_KEY_METADATA_TVDB_ENABLED, state.tvdb_enabled),
        (SET_KEY_METADATA_LANGUAGE, state.language),
        (SET_KEY_METADATA_FALLBACK_LANGUAGE, state.fallback_language),
        (SET_KEY_METADATA_CACHE_ENABLED, state.cache_enabled),
        (SET_KEY_METADATA_CACHE_DAYS, state.cache_days),
    )
    for key, value in values:
        settings.setValue(key, value)
    write_secret(settings, SET_KEY_METADATA_TMDB_READ_TOKEN, state.tmdb_read_token)
    write_secret(settings, SET_KEY_METADATA_TMDB_API_KEY, state.tmdb_api_key)
    write_secret(settings, SET_KEY_METADATA_TVDB_API_KEY, state.tvdb_api_key)
    write_secret(settings, SET_KEY_METADATA_TVDB_PIN, state.tvdb_pin)
    write_secret(settings, SET_KEY_METADATA_TVDB_BEARER_TOKEN, state.tvdb_bearer_token)
    settings.sync()
