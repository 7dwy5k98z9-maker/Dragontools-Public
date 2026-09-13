# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Any

from .german_title_variants import german_umlaut_search_variants
from .online_metadata_common import (
    EpisodeMetadataSuggestion,
    MovieMetadataSuggestion,
    OnlineMetadataError,
    SeriesMetadataSuggestion,
    _clear_cache_dir,
    _float_or_none,
    _int_or_none,
    normalize_episode_metadata_title,
    parse_series_query,
)
from .online_metadata_tvdb_candidates import resolve_episode_candidates as _resolve_episode_candidates
from .online_metadata_tvdb_helpers import (
    _records_from_data,
    _tvdb_language_code,
    _tvdb_record_id,
    _tvdb_text,
    _year_from_tvdb_record,
)


class TvdbResolverMixin:
    def test_connection(self) -> dict[str, Any]:
        return self._request_json("/search", {"query": "test", "type": "series", "limit": 1})

    def search_movies(self, query: str, *, year: int | None = None, language: str | None = None) -> list[dict[str, Any]]:
        return self._search_records("movie", query, year=year, language=language)

    def search_series(self, query: str, *, year: int | None = None, language: str | None = None) -> list[dict[str, Any]]:
        return self._search_records("series", query, year=year, language=language)

    def _search_records(self, kind: str, query: str, *, year: int | None, language: str | None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"query": query, "type": kind, "limit": 10}
        if language:
            params["language"] = _tvdb_language_code(language)
        records = _records_from_data(self._request_json("/search", params))
        for record in records:
            record.setdefault("provider", "thetvdb")
            record.setdefault("provider_id", _tvdb_record_id(record))
        if year:
            matching = [record for record in records if _year_from_tvdb_record(record) == year]
            if matching:
                return matching
        return records

    def movie_details(self, movie_id: int, *, include_translations: bool = False) -> dict[str, Any]:
        params = {"meta": "translations"} if include_translations else {}
        return self._request_json(f"/movies/{int(movie_id)}/extended", params)

    def resolve_series(self, query: str, *, year: int | None = None) -> SeriesMetadataSuggestion | None:
        for variant in german_umlaut_search_variants(query) or (query,):
            results = self._search_with_fallback("series", variant, year)
            if results:
                selected = self._select_best_result(results, query, year)
                if selected:
                    return self._series_suggestion_from_record(query, year, selected)
        return None

    def resolve_movie(self, query: str, *, year: int | None = None) -> MovieMetadataSuggestion | None:
        for variant in german_umlaut_search_variants(query) or (query,):
            results = self._search_with_fallback("movie", variant, year)
            if results:
                selected = self._select_best_result(results, query, year)
                if selected:
                    return self._movie_suggestion_from_record(query, year, selected)
        return None

    def _search_with_fallback(self, kind: str, query: str, year: int | None) -> list[dict[str, Any]]:
        search = self.search_series if kind == "series" else self.search_movies
        results = search(query, year=year, language=self.config.language)
        if not results and self.config.fallback_language != self.config.language:
            results = search(query, year=year, language=self.config.fallback_language)
        return results

    def resolve_episode_file(self, path: str | Path) -> EpisodeMetadataSuggestion | None:
        try:
            from ..rules.move_rules import parse_series_match_details
        except Exception:
            return None
        parsed = parse_series_match_details(Path(path).name)
        if not parsed or not parsed.get("series"):
            return None
        series_query = parse_series_query(Path(path).name)
        series = self.resolve_series(str(parsed["series"]), year=series_query.year)
        if series is None:
            return None
        season, episode = int(parsed.get("season") or 0), int(parsed.get("episode") or 0)
        if season < 0 or episode <= 0:
            return None
        selected = self.resolve_episode_record(series.tmdb_id, season, episode)
        if selected is None:
            return None
        episode_id = _int_or_none(selected.get("id") or selected.get("tvdb_id") or selected.get("tvdbId") or selected.get("episode_id")) or 0
        title, title_is_fallback = normalize_episode_metadata_title(
            _tvdb_text(selected, "name_translated", "name", "title"),
            episode,
            source_path=path,
        )
        return EpisodeMetadataSuggestion(
            query_series=str(parsed["series"]),
            series_tmdb_id=series.tmdb_id,
            episode_tmdb_id=episode_id,
            show_name=series.name,
            original_show_name=series.original_name,
            season_number=season,
            episode_number=episode,
            title=title,
            overview=_tvdb_text(selected, "overview", "overview_translated"),
            air_date=str(selected.get("aired") or selected.get("firstAired") or selected.get("air_date") or "").strip(),
            runtime_min=_int_or_none(selected.get("runtime") or selected.get("runtime_min")),
            vote_average=_float_or_none(selected.get("score")),
            provider="thetvdb",
            series_provider_id=series.tmdb_id,
            episode_provider_id=episode_id,
            title_is_fallback=title_is_fallback,
        )

    def resolve_episode_candidates(self, path: str | Path, *, limit: int = 6, force_refresh: bool = False) -> tuple[EpisodeMetadataSuggestion, ...]:
        return _resolve_episode_candidates(
            self,
            path,
            limit=limit,
            series_builder=self._series_suggestion_from_record,
            force_refresh=force_refresh,
        )

    def refresh_episode_candidates(
        self, path: str | Path, *, limit: int = 6
    ) -> tuple[EpisodeMetadataSuggestion, ...]:
        return self.resolve_episode_candidates(path, limit=limit, force_refresh=True)

    def clear_cache(self) -> int:
        return _clear_cache_dir(self.cache_dir)
