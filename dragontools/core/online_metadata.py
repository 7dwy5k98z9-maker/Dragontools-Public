# -*- coding: utf-8 -*-
"""Stabile Kompatibilitaets-Fassade fuer die Online-Metadaten-API.

Die fachliche Implementierung ist nach Provider und Verantwortung aufgeteilt.
Bestehende Importe aus ``dragontools.core.online_metadata`` bleiben kompatibel.
"""
from __future__ import annotations

from .online_metadata_common import (
    METADATA_PROVIDERS,
    METADATA_SINGLE_PROVIDERS,
    TMDB_API_BASE,
    TMDB_TIMEOUT_S,
    TVDB_API_BASE,
    TVDB_TIMEOUT_S,
    EpisodeMetadataSuggestion,
    MovieMetadataSuggestion,
    OnlineMetadataAuthError,
    OnlineMetadataConfig,
    OnlineMetadataError,
    ParsedMovieQuery,
    ParsedSeriesQuery,
    SeriesMetadataSuggestion,
    clean_tmdb_collection_name,
    clear_default_metadata_cache,
    config_from_settings,
    default_episode_title,
    default_metadata_cache_dir,
    metadata_provider_configured,
    metadata_series_folder_title,
    normalize_episode_metadata_title,
    parse_movie_query,
    parse_series_query,
)
from .online_metadata_tmdb import TmdbClient
from .online_metadata_tvdb import TheTvdbClient
from .online_metadata_service import (
    CompositeMetadataClient,
    client_from_config,
    client_from_settings,
    client_from_settings_for,
    format_movie_suggestion,
    format_series_suggestion,
    suggest_episode_metadata_for_file,
    suggest_movie_metadata_for_file,
    suggest_series_metadata_for_name,
)

__all__ = [
    "METADATA_PROVIDERS",
    "METADATA_SINGLE_PROVIDERS",
    "TMDB_API_BASE",
    "TMDB_TIMEOUT_S",
    "TVDB_API_BASE",
    "TVDB_TIMEOUT_S",
    "OnlineMetadataError",
    "OnlineMetadataAuthError",
    "OnlineMetadataConfig",
    "ParsedMovieQuery",
    "ParsedSeriesQuery",
    "MovieMetadataSuggestion",
    "SeriesMetadataSuggestion",
    "EpisodeMetadataSuggestion",
    "metadata_series_folder_title",
    "config_from_settings",
    "metadata_provider_configured",
    "parse_movie_query",
    "parse_series_query",
    "clean_tmdb_collection_name",
    "default_metadata_cache_dir",
    "clear_default_metadata_cache",
    "default_episode_title",
    "normalize_episode_metadata_title",
    "TmdbClient",
    "TheTvdbClient",
    "CompositeMetadataClient",
    "client_from_settings",
    "client_from_config",
    "client_from_settings_for",
    "suggest_movie_metadata_for_file",
    "suggest_series_metadata_for_name",
    "suggest_episode_metadata_for_file",
    "format_movie_suggestion",
    "format_series_suggestion",
]
