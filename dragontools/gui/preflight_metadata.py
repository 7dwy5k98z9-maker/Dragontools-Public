# -*- coding: utf-8 -*-
"""Orchestrierung der Hintergrund-Metadatensuche für den Preflight-Dialog."""
from __future__ import annotations

from collections.abc import Callable
from PyQt6.QtCore import QSettings

from ..core.settings import APP_NAME, APP_ORG
from .preflight_metadata_apply import apply_metadata_result
from .preflight_metadata_common import MetadataLookupCache
from .preflight_metadata_movie import resolve_movie_metadata
from .preflight_metadata_series import resolve_series_metadata


def online_metadata_enabled() -> bool:
    try:
        from ..core.online_metadata import config_from_settings, metadata_provider_configured
        cfg = config_from_settings(QSettings(APP_ORG, APP_NAME), require_enabled=False)
        return metadata_provider_configured(cfg, "movie") or metadata_provider_configured(cfg, "series")
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        return False


def media_library_preflight_enabled() -> bool:
    try:
        from ..core.media_library import default_media_library_db_path
        from ..core.settings import (
            SET_KEY_MEDIA_LIBRARY_DB_PATH,
            SET_KEY_MEDIA_LIBRARY_ENABLED,
            SET_KEY_MEDIA_LIBRARY_PREFLIGHT_ENABLED,
        )
        settings = QSettings(APP_ORG, APP_NAME)
        if not settings.value(SET_KEY_MEDIA_LIBRARY_ENABLED, False, type=bool):
            return False
        if not settings.value(SET_KEY_MEDIA_LIBRARY_PREFLIGHT_ENABLED, True, type=bool):
            return False
        db_path = settings.value(
            SET_KEY_MEDIA_LIBRARY_DB_PATH, str(default_media_library_db_path()), type=str
        )
        return bool(str(db_path or "").strip())
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        return False


def run_metadata_lookup(
    jobs,
    result_queue,
    *,
    online_enabled: bool = True,
    is_cancelled: Callable[[], bool] | None = None,
) -> None:
    is_cancelled = is_cancelled or (lambda: False)
    try:
        from ..core.media_library import find_movie_dir_from_settings, find_series_dir_from_settings
        from ..core.online_metadata import (
            parse_movie_query,
            suggest_movie_metadata_for_file,
            suggest_series_metadata_for_name,
        )
        from ..rules.move_rules import find_series_dir_candidates
        settings = QSettings(APP_ORG, APP_NAME)
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        for kind, key, _payload in jobs:
            result_queue.put((kind, key, {"__error__": str(exc)}))
        result_queue.put(("done", "", None))
        return

    cache = MetadataLookupCache()
    try:
        for kind, key, payload in jobs:
            if is_cancelled():
                break
            try:
                if kind == "movie":
                    result = resolve_movie_metadata(
                        payload,
                        settings=settings,
                        online_enabled=online_enabled,
                        cache=cache,
                        parse_movie_query=parse_movie_query,
                        find_movie_dir_from_settings=find_movie_dir_from_settings,
                        suggest_movie_metadata_for_file=suggest_movie_metadata_for_file,
                    )
                elif kind == "series":
                    result = resolve_series_metadata(
                        payload,
                        settings=settings,
                        online_enabled=online_enabled,
                        cache=cache,
                        find_series_dir_from_settings=find_series_dir_from_settings,
                        find_series_dir_candidates=find_series_dir_candidates,
                        suggest_series_metadata_for_name=suggest_series_metadata_for_name,
                    )
                else:
                    result = None
                result_queue.put((kind, key, result))
            except Exception as exc:  # Provider-/DB-Grenze: Fehler als GUI-Ergebnis transportieren.
                result_queue.put((kind, key, {"__error__": str(exc)}))
    finally:
        result_queue.put(("done", "", None))


__all__ = [
    "online_metadata_enabled",
    "media_library_preflight_enabled",
    "run_metadata_lookup",
    "apply_metadata_result",
]
