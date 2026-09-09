# -*- coding: utf-8 -*-
"""Kompatibilitätsfassade für gemeinsame Online-Metadaten-Bausteine."""
from __future__ import annotations

from .online_metadata_types import (
    TMDB_API_BASE, TMDB_TIMEOUT_S, TVDB_API_BASE, TVDB_TIMEOUT_S,
    METADATA_PROVIDERS, METADATA_SINGLE_PROVIDERS,
    OnlineMetadataError, OnlineMetadataAuthError, OnlineMetadataConfig,
    ParsedMovieQuery, ParsedSeriesQuery, MovieMetadataSuggestion,
    SeriesMetadataSuggestion, EpisodeMetadataSuggestion,
    _metadata_provider_value, _metadata_single_provider_value,
    _metadata_provider_enabled, _metadata_provider_error,
    metadata_series_folder_title, default_episode_title, normalize_episode_metadata_title,
)
from .online_metadata_config import (
    config_from_settings, _ensure_metadata_provider_available, metadata_provider_configured,
)
from .online_metadata_parsing import (
    parse_movie_query, parse_series_query, clean_tmdb_collection_name,
    ParsedMetadataResolverMixin, compare_metadata_text,
)
from .online_metadata_cache_paths import (
    default_metadata_cache_dir, clear_default_metadata_cache, _clear_cache_dir,
)
from .online_metadata_payload import (
    _year_from_date, _int_or_none, _float_or_none, _names_from_dicts,
    _credit_names, _actors_from_credits, _movie_tags,
    _certification_from_release_dates, _trailer_url,
)
