# -*- coding: utf-8 -*-
"""Laden und Validieren der Online-Metadaten-Konfiguration."""
from __future__ import annotations

import logging
from collections.abc import Callable

from .secret_settings import read_secret, write_secret
from .settings_access import app_qsettings, sync_settings_checked
from .settings_metadata import DEFAULT_METADATA_CACHE_DAYS, DEFAULT_METADATA_CACHE_ENABLED, DEFAULT_METADATA_FALLBACK_LANGUAGE, DEFAULT_METADATA_LANGUAGE, DEFAULT_METADATA_MOVIE_PROVIDER, DEFAULT_METADATA_SERIES_PROVIDER, DEFAULT_METADATA_MOVIE_PREFERRED_PROVIDER, DEFAULT_METADATA_SERIES_PREFERRED_PROVIDER, SET_KEY_METADATA_CACHE_DAYS, SET_KEY_METADATA_CACHE_ENABLED, SET_KEY_METADATA_FALLBACK_LANGUAGE, SET_KEY_METADATA_LANGUAGE, SET_KEY_METADATA_MOVIE_PROVIDER, SET_KEY_METADATA_SERIES_PROVIDER, SET_KEY_METADATA_MOVIE_PREFERRED_PROVIDER, SET_KEY_METADATA_SERIES_PREFERRED_PROVIDER, SET_KEY_METADATA_TMDB_API_KEY, SET_KEY_METADATA_TMDB_ENABLED, SET_KEY_METADATA_TMDB_READ_TOKEN, SET_KEY_METADATA_TVDB_API_KEY, SET_KEY_METADATA_TVDB_BEARER_TOKEN, SET_KEY_METADATA_TVDB_ENABLED, SET_KEY_METADATA_TVDB_PIN
from .online_metadata_types import (
    OnlineMetadataAuthError, OnlineMetadataConfig,
    _metadata_provider_enabled, _metadata_provider_error,
    _metadata_provider_value, _metadata_single_provider_value,
)

_LOG = logging.getLogger(__name__)


def _is_real_qsettings_instance(settings) -> bool:
    cls = type(settings)
    return cls.__name__ == "QSettings" and str(cls.__module__).startswith("PyQt6.")


def _tvdb_settings_target_factory(settings) -> Callable[[], object] | None:
    """Return a settings factory safe for worker-thread token maintenance."""
    if settings is None:
        return None
    if _is_real_qsettings_instance(settings):
        # Do not mutate the GUI-thread QSettings instance from metadata workers.
        if all(callable(getattr(settings, name, None)) for name in ('fileName', 'format', 'group')):
            settings_class = type(settings)
            filename, format_value, group = settings.fileName(), settings.format(), settings.group()
            def target():
                store = settings_class(filename, format_value)
                if group:
                    store.beginGroup(group)
                return store
            return target
        return app_qsettings
    if callable(getattr(settings, "setValue", None)) and callable(getattr(settings, "sync", None)):
        return lambda: settings
    return None


def _tvdb_bearer_token_accessors_from_settings(
    settings,
) -> tuple[Callable[[], str] | None, Callable[[str], None] | None]:
    target_factory = _tvdb_settings_target_factory(settings)
    if target_factory is None:
        return None, None

    def load() -> str:
        target = target_factory()
        if target is None:
            raise RuntimeError("TheTVDB Bearer-Token konnte nicht aus den Einstellungen gelesen werden.")
        return read_secret(target, SET_KEY_METADATA_TVDB_BEARER_TOKEN).strip()

    def persist(token: str) -> None:
        target = target_factory()
        if target is None:
            raise RuntimeError("TheTVDB Bearer-Token konnte nicht in den Einstellungen gespeichert werden.")
        write_secret(target, SET_KEY_METADATA_TVDB_BEARER_TOKEN, str(token or "").strip())
        sync_settings_checked(target)

    return load, persist


def config_from_settings(
    settings,
    *,
    require_enabled: bool = False,
    media_type: str = "any",
) -> OnlineMetadataConfig:
    tvdb_token_load, tvdb_token_store = _tvdb_bearer_token_accessors_from_settings(settings)
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
        tmdb_api_key=read_secret(settings, SET_KEY_METADATA_TMDB_API_KEY).strip(),
        tmdb_read_token=read_secret(settings, SET_KEY_METADATA_TMDB_READ_TOKEN).strip(),
        tvdb_enabled=settings.value(SET_KEY_METADATA_TVDB_ENABLED, False, type=bool),
        tvdb_api_key=read_secret(settings, SET_KEY_METADATA_TVDB_API_KEY).strip(),
        tvdb_pin=read_secret(settings, SET_KEY_METADATA_TVDB_PIN).strip(),
        tvdb_bearer_token=read_secret(settings, SET_KEY_METADATA_TVDB_BEARER_TOKEN).strip(),
        tvdb_bearer_token_load=tvdb_token_load,
        tvdb_bearer_token_store=tvdb_token_store,
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
