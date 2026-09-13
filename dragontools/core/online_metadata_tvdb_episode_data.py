# -*- coding: utf-8 -*-
"""TheTVDB series/episode data loading and per-client batch reuse."""
from __future__ import annotations

from typing import Any

from .online_metadata_common import OnlineMetadataError
from .online_metadata_tvdb_helpers import (
    _episode_title_is_fallback,
    _episodes_from_tvdb_response,
    _merge_episode_language_fallback,
    _tvdb_language_code,
)


class TvdbEpisodeDataMixin:
    """Load series details/episodes once per provider session when possible."""

    def series_details(
        self,
        series_id: int,
        *,
        include_translations: bool = False,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        key = (int(series_id), bool(include_translations))
        cache = getattr(self, "_series_details_batch_cache", None)
        fresh = getattr(self, "_series_details_batch_fresh", None)
        lock = getattr(self, "_episode_batch_lock", None)

        def cached_value() -> dict[str, Any] | None:
            if cache is None or key not in cache:
                return None
            if force_refresh and fresh is not None and key not in fresh:
                return None
            return dict(cache[key])

        params = {"meta": "translations"} if include_translations else {}
        if lock is None:
            existing = cached_value()
            if existing is not None:
                return existing
            return self._request_json(
                f"/series/{int(series_id)}/extended", params, force_refresh=force_refresh
            )

        with lock:
            existing = cached_value()
            if existing is not None:
                return existing
            payload = self._request_json(
                f"/series/{int(series_id)}/extended", params, force_refresh=force_refresh
            )
            if cache is not None:
                cache[key] = dict(payload)
            if force_refresh and fresh is not None:
                fresh.add(key)
            return dict(payload)

    def series_episodes(
        self,
        series_id: int,
        *,
        season_type: str = "default",
        language: str | None = None,
        force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        lang = _tvdb_language_code(language or self.config.language)
        cache_key = (int(series_id), str(season_type), lang)
        lock = getattr(self, "_episode_batch_lock", None)
        cache = getattr(self, "_episode_batch_cache", None)
        fresh_keys = getattr(self, "_episode_batch_fresh", None)

        def cached_value() -> list[dict[str, Any]] | None:
            if cache is None or cache_key not in cache:
                return None
            if force_refresh and fresh_keys is not None and cache_key not in fresh_keys:
                return None
            return [dict(item) for item in cache[cache_key]]

        if lock is None:
            existing = cached_value()
            if existing is not None:
                return existing
            return self._load_series_episodes(
                series_id, season_type=season_type, lang=lang, force_refresh=force_refresh
            )

        with lock:
            existing = cached_value()
            if existing is not None:
                return existing
            episodes = self._load_series_episodes(
                series_id, season_type=season_type, lang=lang, force_refresh=force_refresh
            )
            if cache is not None:
                cache[cache_key] = [dict(item) for item in episodes]
            if force_refresh and fresh_keys is not None:
                fresh_keys.add(cache_key)
            return [dict(item) for item in episodes]

    def _load_series_episodes(
        self,
        series_id: int,
        *,
        season_type: str,
        lang: str,
        force_refresh: bool,
    ) -> list[dict[str, Any]]:
        endpoints = (
            f"/series/{int(series_id)}/episodes/{season_type}/{lang}",
            f"/series/{int(series_id)}/episodes/{season_type}",
        )
        last_error: OnlineMetadataError | None = None
        for endpoint in endpoints:
            try:
                return _episodes_from_tvdb_response(
                    self._request_json(endpoint, {}, force_refresh=force_refresh)
                )
            except OnlineMetadataError as exc:
                last_error = exc
        if last_error:
            raise last_error
        return []

    def resolve_episode_record(
        self,
        series_id: int,
        season: int,
        episode: int,
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any] | None:
        selected = self._episode_record_for_language(
            series_id, season, episode, self.config.language, force_refresh=force_refresh
        )
        if selected is not None and _episode_title_is_fallback(selected, episode) and not force_refresh:
            selected = self._episode_record_for_language(
                series_id, season, episode, self.config.language, force_refresh=True
            )

        needs_fallback = selected is None or _episode_title_is_fallback(selected, episode)
        if needs_fallback and self.config.fallback_language != self.config.language:
            fallback = self._episode_record_for_language(
                series_id, season, episode, self.config.fallback_language, force_refresh=force_refresh
            )
            if fallback is not None and _episode_title_is_fallback(fallback, episode) and not force_refresh:
                fallback = self._episode_record_for_language(
                    series_id, season, episode, self.config.fallback_language, force_refresh=True
                )
            if fallback is not None:
                if selected is None:
                    selected = fallback
                elif not _episode_title_is_fallback(fallback, episode):
                    selected = _merge_episode_language_fallback(selected, fallback, episode)
        return selected

    def _episode_record_for_language(
        self,
        series_id: int,
        season: int,
        episode: int,
        language: str,
        *,
        force_refresh: bool,
    ) -> dict[str, Any] | None:
        episodes = self.series_episodes(
            series_id, language=language, force_refresh=force_refresh
        )
        return self._find_episode(episodes, season, episode)
