# -*- coding: utf-8 -*-
"""Datentypen, Provider-Konstanten und elementare Metadatenregeln."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..rules.renamer_rules import sanitize_renamer_text
from .settings import (
    DEFAULT_METADATA_CACHE_DAYS,
    DEFAULT_METADATA_CACHE_ENABLED,
    DEFAULT_METADATA_FALLBACK_LANGUAGE,
    DEFAULT_METADATA_LANGUAGE,
    DEFAULT_METADATA_MOVIE_PROVIDER,
    DEFAULT_METADATA_SERIES_PROVIDER,
    DEFAULT_METADATA_MOVIE_PREFERRED_PROVIDER,
    DEFAULT_METADATA_SERIES_PREFERRED_PROVIDER,
)

TMDB_API_BASE = "https://api.themoviedb.org/3"
TMDB_TIMEOUT_S = 12
TVDB_API_BASE = "https://api4.thetvdb.com/v4"
TVDB_TIMEOUT_S = 15
METADATA_PROVIDERS = ("tmdb", "thetvdb", "both")
METADATA_SINGLE_PROVIDERS = ("tmdb", "thetvdb")


class OnlineMetadataError(RuntimeError):
    pass


class OnlineMetadataAuthError(OnlineMetadataError):
    pass


@dataclass(frozen=True)
class OnlineMetadataConfig:
    movie_provider: str = DEFAULT_METADATA_MOVIE_PROVIDER
    series_provider: str = DEFAULT_METADATA_SERIES_PROVIDER
    movie_preferred_provider: str = DEFAULT_METADATA_MOVIE_PREFERRED_PROVIDER
    series_preferred_provider: str = DEFAULT_METADATA_SERIES_PREFERRED_PROVIDER
    tmdb_enabled: bool = False
    tmdb_api_key: str = ""
    tmdb_read_token: str = ""
    tvdb_enabled: bool = False
    tvdb_api_key: str = ""
    tvdb_pin: str = ""
    tvdb_bearer_token: str = ""
    language: str = DEFAULT_METADATA_LANGUAGE
    fallback_language: str = DEFAULT_METADATA_FALLBACK_LANGUAGE
    cache_enabled: bool = DEFAULT_METADATA_CACHE_ENABLED
    cache_days: int = DEFAULT_METADATA_CACHE_DAYS

    @property
    def has_tmdb_credentials(self) -> bool:
        return bool(self.tmdb_read_token.strip() or self.tmdb_api_key.strip())

    @property
    def has_tvdb_credentials(self) -> bool:
        return bool(self.tvdb_bearer_token.strip() or self.tvdb_api_key.strip())

    def provider_for(self, media_type: str) -> str:
        if media_type == "series":
            return _metadata_provider_value(self.series_provider, DEFAULT_METADATA_SERIES_PROVIDER)
        return _metadata_provider_value(self.movie_provider, DEFAULT_METADATA_MOVIE_PROVIDER)

    def preferred_provider_for(self, media_type: str) -> str:
        if media_type == "series":
            return _metadata_single_provider_value(
                self.series_preferred_provider,
                DEFAULT_METADATA_SERIES_PREFERRED_PROVIDER,
            )
        return _metadata_single_provider_value(
            self.movie_preferred_provider,
            DEFAULT_METADATA_MOVIE_PREFERRED_PROVIDER,
        )

    def provider_chain_for(self, media_type: str) -> tuple[str, ...]:
        provider = self.provider_for(media_type)
        if provider == "both":
            preferred = self.preferred_provider_for(media_type)
            other = "thetvdb" if preferred == "tmdb" else "tmdb"
            return (preferred, other)
        return (provider,)


@dataclass(frozen=True)
class ParsedMovieQuery:
    title: str
    year: int | None = None


@dataclass(frozen=True)
class ParsedSeriesQuery:
    title: str
    year: int | None = None


def _metadata_provider_value(value: str, default: str = "tmdb") -> str:
    provider = str(value or "").strip().lower()
    return provider if provider in METADATA_PROVIDERS else default


def _metadata_single_provider_value(value: str, default: str = "tmdb") -> str:
    provider = str(value or "").strip().lower()
    return provider if provider in METADATA_SINGLE_PROVIDERS else default


def _metadata_provider_enabled(cfg: OnlineMetadataConfig, provider: str) -> bool:
    if provider == "thetvdb":
        return bool(cfg.tvdb_enabled and cfg.has_tvdb_credentials)
    return bool(cfg.tmdb_enabled and cfg.has_tmdb_credentials)


def _metadata_provider_error(cfg: OnlineMetadataConfig, provider: str) -> str:
    if provider == "thetvdb":
        if not cfg.tvdb_enabled:
            return "TheTVDB ist nicht aktiviert."
        if not cfg.has_tvdb_credentials:
            return "Kein TheTVDB API-Key, PIN oder Bearer-Token hinterlegt."
        return ""
    if not cfg.tmdb_enabled:
        return "TMDB ist nicht aktiviert."
    if not cfg.has_tmdb_credentials:
        return "Kein TMDB API-Key oder Read-Access-Token hinterlegt."
    return ""


def metadata_series_folder_title(value: str) -> str:
    """Bereinigt Provider-Serientitel mit exakt den Renamer-Zeichenregeln.

    Damit erzeugen Renamer, Preflight und Zielordner dieselbe lokale
    Schreibweise. Beispiel bei Standardregeln:
    ``Kaguya-sama: Love Is War`` -> ``Kaguya-sama Love Is War``.
    """
    return sanitize_renamer_text(value, fallback="")


@dataclass(frozen=True)
class MovieMetadataSuggestion:
    query_title: str
    query_year: int | None
    tmdb_id: int
    title: str
    original_title: str
    release_year: int | None
    overview: str = ""
    tagline: str = ""
    release_date: str = ""
    runtime_min: int | None = None
    vote_average: float | None = None
    certification: str = ""
    imdb_id: str = ""
    countries: tuple[str, ...] = ()
    genres: tuple[str, ...] = ()
    studios: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    directors: tuple[str, ...] = ()
    writers: tuple[str, ...] = ()
    actors: tuple[dict[str, Any], ...] = ()
    trailer_url: str = ""
    collection_id: int | None = None
    collection_name: str = ""
    collection_part_count: int = 0
    provider: str = "tmdb"
    provider_id: int | None = None

    @property
    def has_collection(self) -> bool:
        return bool(self.collection_id and self.collection_name.strip())

    @property
    def movie_folder_name(self) -> str:
        title = self.title.strip() or self.original_title.strip() or self.query_title
        if self.release_year:
            return f"{title} ({self.release_year})"
        return title


@dataclass(frozen=True)
class SeriesMetadataSuggestion:
    query_title: str
    query_year: int | None
    tmdb_id: int
    name: str
    original_name: str
    first_air_year: int | None
    overview: str = ""
    first_air_date: str = ""
    provider: str = "tmdb"
    provider_id: int | None = None

    @property
    def folder_name(self) -> str:
        title = (
            metadata_series_folder_title(self.name)
            or metadata_series_folder_title(self.original_name)
            or metadata_series_folder_title(self.query_title)
            or self.query_title
        )
        if self.first_air_year:
            return f"{title} ({self.first_air_year})"
        return title


@dataclass(frozen=True)
class EpisodeMetadataSuggestion:
    query_series: str
    series_tmdb_id: int
    episode_tmdb_id: int
    show_name: str
    original_show_name: str
    season_number: int
    episode_number: int
    title: str
    first_air_year: int | None = None  # DragonTools patch: episode first-air-year v3
    overview: str = ""
    air_date: str = ""
    runtime_min: int | None = None
    vote_average: float | None = None
    imdb_id: str = ""
    directors: tuple[str, ...] = ()
    writers: tuple[str, ...] = ()
    actors: tuple[dict[str, Any], ...] = ()
    provider: str = "tmdb"
    series_provider_id: int | None = None
    episode_provider_id: int | None = None
    title_is_fallback: bool = False


_GENERIC_EPISODE_TITLE_RE = re.compile(r"^(?:episode|ep\.?|folge)\s*#?\s*0*(\d{1,3})$", re.IGNORECASE)
_GENERIC_EPISODE_CODE_RE = re.compile(r"^S\d{1,2}E0*(\d{1,3})$", re.IGNORECASE)


def default_episode_title(episode: int) -> str:
    """Deterministischer deutscher Fallback fuer noch unbenannte Episoden."""
    return f"Folge {max(0, int(episode)):02d}"


def normalize_episode_metadata_title(
    value: Any,
    episode: int,
    *,
    source_path: str | Path | None = None,
) -> tuple[str, bool]:
    """Liefert ``(title, is_fallback)`` ohne Release-Dateinamen als Titel.

    Leere oder generische Provider-Titel werden auf ``Folge XX`` normalisiert.
    Ein versehentlich uebernommener Quell-Dateistem wird ebenfalls verworfen.
    """
    text = re.sub(r"\s+", " ", str(value or "")).strip(" .-_")
    fallback = default_episode_title(episode)
    if not text:
        return fallback, True
    if source_path is not None:
        source_stem = Path(str(source_path)).stem.strip()
        if source_stem and text.casefold() == source_stem.casefold():
            return fallback, True
    match = _GENERIC_EPISODE_TITLE_RE.fullmatch(text)
    if match and int(match.group(1)) == int(episode):
        return fallback, True
    match = _GENERIC_EPISODE_CODE_RE.fullmatch(text)
    if match and int(match.group(1)) == int(episode):
        return fallback, True
    return text, False
