# -*- coding: utf-8 -*-
"""Online metadata provider setting keys and secret classification."""
from __future__ import annotations

SET_KEY_METADATA_MOVIE_PROVIDER = "metadata/provider/movie"
SET_KEY_METADATA_SERIES_PROVIDER = "metadata/provider/series"
SET_KEY_METADATA_MOVIE_PREFERRED_PROVIDER = "metadata/provider/movie_preferred"
SET_KEY_METADATA_SERIES_PREFERRED_PROVIDER = "metadata/provider/series_preferred"
SET_KEY_METADATA_TMDB_ENABLED = "metadata/tmdb/enabled"
SET_KEY_METADATA_TMDB_API_KEY = "metadata/tmdb/api_key"
SET_KEY_METADATA_TMDB_READ_TOKEN = "metadata/tmdb/read_access_token"
SET_KEY_METADATA_TVDB_ENABLED = "metadata/thetvdb/enabled"
SET_KEY_METADATA_TVDB_API_KEY = "metadata/thetvdb/api_key"
SET_KEY_METADATA_TVDB_PIN = "metadata/thetvdb/pin"
SET_KEY_METADATA_TVDB_BEARER_TOKEN = "metadata/thetvdb/bearer_token"
SET_KEY_METADATA_LANGUAGE = "metadata/language"
SET_KEY_METADATA_FALLBACK_LANGUAGE = "metadata/fallback_language"
SET_KEY_METADATA_CACHE_ENABLED = "metadata/cache_enabled"
SET_KEY_METADATA_CACHE_DAYS = "metadata/cache_days"

DEFAULT_METADATA_MOVIE_PROVIDER = "tmdb"
DEFAULT_METADATA_SERIES_PROVIDER = "tmdb"
DEFAULT_METADATA_MOVIE_PREFERRED_PROVIDER = "tmdb"
DEFAULT_METADATA_SERIES_PREFERRED_PROVIDER = "tmdb"
DEFAULT_METADATA_LANGUAGE = "de-DE"
DEFAULT_METADATA_FALLBACK_LANGUAGE = "en-US"
DEFAULT_METADATA_CACHE_ENABLED = True
DEFAULT_METADATA_CACHE_DAYS = 30

SENSITIVE_SETTINGS_KEYS = {
    SET_KEY_METADATA_TMDB_API_KEY,
    SET_KEY_METADATA_TMDB_READ_TOKEN,
    SET_KEY_METADATA_TVDB_API_KEY,
    SET_KEY_METADATA_TVDB_PIN,
    SET_KEY_METADATA_TVDB_BEARER_TOKEN,
}

__all__ = [
    name for name in globals()
    if name.startswith(("SET_KEY_", "DEFAULT_", "SENSITIVE_"))
]
