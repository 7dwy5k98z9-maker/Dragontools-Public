# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Any

from .online_metadata_common import (
    EpisodeMetadataSuggestion,
    MovieMetadataSuggestion,
    OnlineMetadataAuthError,
    OnlineMetadataConfig,
    OnlineMetadataError,
    ParsedMetadataResolverMixin,
    SeriesMetadataSuggestion,
    _ensure_metadata_provider_available,
    _metadata_provider_enabled,
    config_from_settings,
)
from .online_metadata_tmdb import TmdbClient
from .online_metadata_tvdb import TheTvdbClient


class CompositeMetadataClient(ParsedMetadataResolverMixin):
    def __init__(self, clients: tuple[Any, ...]) -> None:
        self.clients = tuple(clients)
        self.config = self.clients[0].config if self.clients else OnlineMetadataConfig()
        self.provider_order = tuple(
            "thetvdb" if isinstance(client, TheTvdbClient) else "tmdb"
            for client in self.clients
        )
        self.provider_label = " + ".join(
            getattr(client, "provider_label", "Metadaten") for client in self.clients
        )

    def enable_fresh_session(self) -> None:
        """Make all child providers bypass persistent cache once per request."""
        for client in self.clients:
            enable = getattr(client, "enable_fresh_session", None)
            if callable(enable):
                enable()

    def test_connection(self) -> dict[str, Any]:
        data: dict[str, Any] = {"providers": []}
        for client in self.clients:
            client.test_connection()
            data["providers"].append(getattr(client, "provider_label", "Metadaten"))
        return data

    def search_movies(
        self,
        query: str,
        *,
        year: int | None = None,
        language: str | None = None,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for client in self.clients:
            if not hasattr(client, "search_movies"):
                continue
            try:
                provider_results = client.search_movies(query, year=year, language=language)
            except OnlineMetadataError:
                continue
            provider = "thetvdb" if isinstance(client, TheTvdbClient) else "tmdb"
            for item in provider_results:
                record = dict(item)
                record.setdefault("provider", provider)
                record.setdefault(
                    "provider_id",
                    record.get("provider_id") or record.get("id") or record.get("tmdb_id"),
                )
                results.append(record)
        return results

    def resolve_movie(self, query: str, *, year: int | None = None) -> MovieMetadataSuggestion | None:
        # Clients stehen bereits in der vom Benutzer gewählten Priorität.
        # Der zweite Provider ist Fallback, nicht Konkurrent des bevorzugten.
        for client in self.clients:
            if not hasattr(client, "resolve_movie"):
                continue
            try:
                suggestion = client.resolve_movie(query, year=year)
            except OnlineMetadataError:
                continue
            if suggestion is not None:
                return suggestion
        return None

    def resolve_series(self, query: str, *, year: int | None = None) -> SeriesMetadataSuggestion | None:
        # Clients stehen bereits in der vom Benutzer gewählten Priorität.
        for client in self.clients:
            if not hasattr(client, "resolve_series"):
                continue
            try:
                suggestion = client.resolve_series(query, year=year)
            except OnlineMetadataError:
                continue
            if suggestion is not None:
                return suggestion
        return None

    def resolve_episode_file(self, path: str | Path) -> EpisodeMetadataSuggestion | None:
        suggestions = self.resolve_episode_candidates(path)
        return suggestions[0] if suggestions else None

    def resolve_episode_candidates(
        self,
        path: str | Path,
        *,
        limit: int = 6,
    ) -> tuple[EpisodeMetadataSuggestion, ...]:
        return self._episode_candidates(path, limit=limit, force_refresh=False)

    def refresh_episode_candidates(
        self,
        path: str | Path,
        *,
        limit: int = 6,
    ) -> tuple[EpisodeMetadataSuggestion, ...]:
        return self._episode_candidates(path, limit=limit, force_refresh=True)

    def clear_cache(self) -> int:
        return sum(
            int(getattr(client, "clear_cache")())
            for client in self.clients
            if hasattr(client, "clear_cache")
        )

    def _episode_candidates(
        self,
        path: str | Path,
        *,
        limit: int,
        force_refresh: bool,
    ) -> tuple[EpisodeMetadataSuggestion, ...]:
        per_provider_cap = max(1, int(limit))
        results: list[EpisodeMetadataSuggestion] = []
        for client in self.clients:
            bucket: list[EpisodeMetadataSuggestion] = []
            try:
                if force_refresh and hasattr(client, "refresh_episode_candidates"):
                    bucket.extend(
                        client.refresh_episode_candidates(path, limit=per_provider_cap)
                    )
                elif hasattr(client, "resolve_episode_candidates"):
                    bucket.extend(
                        client.resolve_episode_candidates(path, limit=per_provider_cap)
                    )
                elif hasattr(client, "resolve_episode_file"):
                    suggestion = client.resolve_episode_file(path)
                    if suggestion is not None:
                        bucket.append(suggestion)
            except OnlineMetadataError:
                continue
            results.extend(bucket[:per_provider_cap])
        return tuple(results)


def client_from_settings(settings, *, require_enabled: bool = False):
    return client_from_settings_for(settings, "movie", require_enabled=require_enabled)


def _client_for_provider(config: OnlineMetadataConfig, provider: str):
    if provider == "thetvdb":
        if not config.tvdb_enabled:
            raise OnlineMetadataAuthError("TheTVDB ist nicht aktiviert.")
        return TheTvdbClient(config)
    if not config.tmdb_enabled:
        raise OnlineMetadataAuthError("TMDB ist nicht aktiviert.")
    return TmdbClient(config)


def client_from_config(config: OnlineMetadataConfig, media_type: str):
    providers = tuple(
        provider for provider in config.provider_chain_for(media_type)
        if _metadata_provider_enabled(config, provider)
    )
    if not providers:
        _ensure_metadata_provider_available(config, media_type)
    clients = tuple(_client_for_provider(config, provider) for provider in providers)
    if len(clients) == 1:
        return clients[0]
    return CompositeMetadataClient(clients)


def client_from_settings_for(settings, media_type: str, *, require_enabled: bool = False):
    config = config_from_settings(settings, require_enabled=require_enabled, media_type=media_type)
    return client_from_config(config, media_type)


def suggest_movie_metadata_for_file(path: str | Path, settings) -> MovieMetadataSuggestion | None:
    try:
        client = client_from_settings_for(settings, "movie", require_enabled=True)
        return client.resolve_movie_file(path)
    except OnlineMetadataError:
        return None


def suggest_series_metadata_for_name(value: str | Path, settings) -> SeriesMetadataSuggestion | None:
    try:
        client = client_from_settings_for(settings, "series", require_enabled=True)
        return client.resolve_series_name(value)
    except OnlineMetadataError:
        return None


def suggest_episode_metadata_for_file(path: str | Path, settings) -> EpisodeMetadataSuggestion | None:
    try:
        client = client_from_settings_for(settings, "series", require_enabled=True)
        return client.resolve_episode_file(path)
    except OnlineMetadataError:
        return None


def format_movie_suggestion(suggestion: MovieMetadataSuggestion | None) -> str:
    if suggestion is None:
        return "Kein passender Metadaten-Treffer gefunden."
    lines = [
        f"Treffer: {suggestion.movie_folder_name}",
        f"{_provider_label(suggestion.provider)}-ID: {suggestion.provider_id or suggestion.tmdb_id}",
    ]
    if suggestion.original_title and suggestion.original_title != suggestion.title:
        lines.append(f"Originaltitel: {suggestion.original_title}")
    if suggestion.has_collection:
        count = f" ({suggestion.collection_part_count} Teile)" if suggestion.collection_part_count else ""
        lines.append(f"Filmreihe: {suggestion.collection_name}{count}")
    else:
        lines.append("Filmreihe: keine Collection gefunden")
    return "\n".join(lines)


def format_series_suggestion(suggestion: SeriesMetadataSuggestion | None) -> str:
    if suggestion is None:
        return "Kein passender Serien-Treffer gefunden."
    lines = [
        f"Treffer: {suggestion.folder_name}",
        f"{_provider_label(suggestion.provider)}-ID: {suggestion.provider_id or suggestion.tmdb_id}",
    ]
    if suggestion.original_name and suggestion.original_name != suggestion.name:
        lines.append(f"Originaltitel: {suggestion.original_name}")
    if suggestion.first_air_year:
        lines.append(f"Erstausstrahlung: {suggestion.first_air_year}")
    return "\n".join(lines)


def _provider_label(provider: str) -> str:
    return "TheTVDB" if str(provider or "").lower() == "thetvdb" else "TMDB"
