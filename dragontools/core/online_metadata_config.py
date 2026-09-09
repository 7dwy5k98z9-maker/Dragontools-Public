# -*- coding: utf-8 -*-
"""Laden und Validieren der Online-Metadaten-Konfiguration."""
from __future__ import annotations

from .settings import (
    DEFAULT_METADATA_CACHE_DAYS, DEFAULT_METADATA_CACHE_ENABLED,
    DEFAULT_METADATA_FALLBACK_LANGUAGE, DEFAULT_METADATA_LANGUAGE,
    DEFAULT_METADATA_MOVIE_PROVIDER, DEFAULT_METADATA_SERIES_PROVIDER,
    DEFAULT_METADATA_MOVIE_PREFERRED_PROVIDER, DEFAULT_METADATA_SERIES_PREFERRED_PROVIDER,
    SET_KEY_METADATA_CACHE_DAYS, SET_KEY_METADATA_CACHE_ENABLED,
    SET_KEY_METADATA_FALLBACK_LANGUAGE, SET_KEY_METADATA_LANGUAGE,
    SET_KEY_METADATA_MOVIE_PROVIDER, SET_KEY_METADATA_SERIES_PROVIDER,
    SET_KEY_METADATA_MOVIE_PREFERRED_PROVIDER, SET_KEY_METADATA_SERIES_PREFERRED_PROVIDER,
    SET_KEY_METADATA_TMDB_API_KEY, SET_KEY_METADATA_TMDB_ENABLED, SET_KEY_METADATA_TMDB_READ_TOKEN,
    SET_KEY_METADATA_TVDB_API_KEY, SET_KEY_METADATA_TVDB_BEARER_TOKEN,
    SET_KEY_METADATA_TVDB_ENABLED, SET_KEY_METADATA_TVDB_PIN,
)
from .online_metadata_types import (
    OnlineMetadataAuthError, OnlineMetadataConfig,
    _metadata_provider_enabled, _metadata_provider_error,
    _metadata_provider_value, _metadata_single_provider_value,
)

def config_from_settings(
    settings,
    *,
    require_enabled: bool = False,
    media_type: str = "any",
) -> OnlineMetadataConfig:
    cfg = OnlineMetadataConfig(
        movie_provider=_metadata_provider_value(
            settings.value(
                SET_KEY_METADATA_MOVIE_PROVIDER,
                DEFAULT_METADATA_MOVIE_PROVIDER,
                type=str,
            ),
            DEFAULT_METADATA_MOVIE_PROVIDER,
        ),
        series_provider=_metadata_provider_value(
            settings.value(
                SET_KEY_METADATA_SERIES_PROVIDER,
                DEFAULT_METADATA_SERIES_PROVIDER,
                type=str,
            ),
            DEFAULT_METADATA_SERIES_PROVIDER,
        ),
        movie_preferred_provider=_metadata_single_provider_value(
            settings.value(
                SET_KEY_METADATA_MOVIE_PREFERRED_PROVIDER,
                DEFAULT_METADATA_MOVIE_PREFERRED_PROVIDER,
                type=str,
            ),
            DEFAULT_METADATA_MOVIE_PREFERRED_PROVIDER,
        ),
        series_preferred_provider=_metadata_single_provider_value(
            settings.value(
                SET_KEY_METADATA_SERIES_PREFERRED_PROVIDER,
                DEFAULT_METADATA_SERIES_PREFERRED_PROVIDER,
                type=str,
            ),
            DEFAULT_METADATA_SERIES_PREFERRED_PROVIDER,
        ),
        tmdb_enabled=settings.value(SET_KEY_METADATA_TMDB_ENABLED, False, type=bool),
        tmdb_api_key=settings.value(SET_KEY_METADATA_TMDB_API_KEY, "", type=str).strip(),
        tmdb_read_token=settings.value(SET_KEY_METADATA_TMDB_READ_TOKEN, "", type=str).strip(),
        tvdb_enabled=settings.value(SET_KEY_METADATA_TVDB_ENABLED, False, type=bool),
        tvdb_api_key=settings.value(SET_KEY_METADATA_TVDB_API_KEY, "", type=str).strip(),
        tvdb_pin=settings.value(SET_KEY_METADATA_TVDB_PIN, "", type=str).strip(),
        tvdb_bearer_token=settings.value(SET_KEY_METADATA_TVDB_BEARER_TOKEN, "", type=str).strip(),
        language=settings.value(SET_KEY_METADATA_LANGUAGE, DEFAULT_METADATA_LANGUAGE, type=str).strip()
        or DEFAULT_METADATA_LANGUAGE,
        fallback_language=settings.value(
            SET_KEY_METADATA_FALLBACK_LANGUAGE,
            DEFAULT_METADATA_FALLBACK_LANGUAGE,
            type=str,
        ).strip()
        or DEFAULT_METADATA_FALLBACK_LANGUAGE,
        cache_enabled=settings.value(
            SET_KEY_METADATA_CACHE_ENABLED,
            DEFAULT_METADATA_CACHE_ENABLED,
            type=bool,
        ),
        cache_days=max(
            1,
            int(settings.value(SET_KEY_METADATA_CACHE_DAYS, DEFAULT_METADATA_CACHE_DAYS, type=int)),
        ),
    )
    if require_enabled:
        _ensure_metadata_provider_available(cfg, media_type)
    return cfg


def _ensure_metadata_provider_available(cfg: OnlineMetadataConfig, media_type: str) -> None:
    requested: tuple[str, ...]
    if media_type in {"movie", "series"}:
        requested = (media_type,)
    else:
        requested = ("movie", "series")

    errors: list[str] = []
    for typ in requested:
        providers = cfg.provider_chain_for(typ)
        if any(_metadata_provider_enabled(cfg, provider) for provider in providers):
            continue
        provider_errors = [_metadata_provider_error(cfg, provider) for provider in providers]
        provider_errors = [text for text in provider_errors if text]
        if len(providers) > 1:
            errors.append(f"{typ}: Keine der gewählten Metadatenquellen ist vollständig eingerichtet.")
            errors.extend(provider_errors)
        elif provider_errors:
            errors.extend(provider_errors)
    if errors:
        raise OnlineMetadataAuthError(" ".join(dict.fromkeys(errors)))


def metadata_provider_configured(cfg: OnlineMetadataConfig, media_type: str = "any") -> bool:
    try:
        _ensure_metadata_provider_available(cfg, media_type)
        return True
    except OnlineMetadataAuthError:
        return False
