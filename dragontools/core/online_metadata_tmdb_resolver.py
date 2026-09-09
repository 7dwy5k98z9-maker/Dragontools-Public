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
    _actors_from_credits,
    _certification_from_release_dates,
    _clear_cache_dir,
    _credit_names,
    _float_or_none,
    _int_or_none,
    _movie_tags,
    _names_from_dicts,
    _trailer_url,
    _year_from_date,
    clean_tmdb_collection_name,
    normalize_episode_metadata_title,
    parse_series_query,
)


class TmdbResolverMixin:
    """Search/detail endpoints and direct movie/series/episode resolution."""

    def test_connection(self) -> dict[str, Any]:
        return self._request_json("/configuration", {})

    def search_movies(
        self,
        query: str,
        *,
        year: int | None = None,
        language: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "query": query,
            "include_adult": "false",
            "language": language or self.config.language,
            "page": 1,
        }
        if year:
            params["year"] = str(year)
            params["primary_release_year"] = str(year)
        data = self._request_json("/search/movie", params)
        return list(data.get("results") or [])

    def search_tv(
        self,
        query: str,
        *,
        year: int | None = None,
        language: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "query": query,
            "include_adult": "false",
            "language": language or self.config.language,
            "page": 1,
        }
        if year:
            params["first_air_date_year"] = str(year)
        data = self._request_json("/search/tv", params)
        return list(data.get("results") or [])

    def movie_details(
        self,
        movie_id: int,
        *,
        language: str | None = None,
        append_to_response: str = "",
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"language": language or self.config.language}
        if append_to_response:
            params["append_to_response"] = append_to_response
        return self._request_json(f"/movie/{int(movie_id)}", params)

    def tv_details(
        self,
        tv_id: int,
        *,
        language: str | None = None,
        append_to_response: str = "",
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"language": language or self.config.language}
        if append_to_response:
            params["append_to_response"] = append_to_response
        return self._request_json(f"/tv/{int(tv_id)}", params)

    def tv_episode_details(
        self,
        tv_id: int,
        season: int,
        episode: int,
        *,
        language: str | None = None,
        append_to_response: str = "",
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"language": language or self.config.language}
        if append_to_response:
            params["append_to_response"] = append_to_response
        return self._request_json(
            f"/tv/{int(tv_id)}/season/{int(season)}/episode/{int(episode)}",
            params,
        )

    def collection_details(
        self,
        collection_id: int,
        *,
        language: str | None = None,
    ) -> dict[str, Any]:
        return self._request_json(
            f"/collection/{int(collection_id)}",
            {"language": language or self.config.language},
        )

    def resolve_movie(
        self,
        query: str,
        *,
        year: int | None = None,
    ) -> MovieMetadataSuggestion | None:
        results = self._search_movies_with_title_variants(query, year=year)
        if not results:
            return None

        selected = self._select_best_result(results, year, date_key="release_date")
        if not selected:
            return None

        movie_id = int(selected["id"])
        details = self.movie_details(
            movie_id,
            append_to_response="credits,videos,keywords,release_dates,external_ids",
        )
        title = str(details.get("title") or selected.get("title") or query).strip()
        original_title = str(
            details.get("original_title") or selected.get("original_title") or title
        ).strip()
        release_year = (
            _year_from_date(details.get("release_date") or selected.get("release_date"))
            or year
        )
        collection = dict(details.get("belongs_to_collection") or {})
        collection_id = _int_or_none(collection.get("id"))
        collection_name = str(collection.get("name") or "").strip()
        part_count = 0
        if collection_id:
            try:
                collection_details = self.collection_details(collection_id)
                collection_name = str(
                    collection_details.get("name") or collection_name
                ).strip()
                part_count = len(collection_details.get("parts") or [])
            except OnlineMetadataError:
                part_count = 0
        collection_name = clean_tmdb_collection_name(collection_name)

        return MovieMetadataSuggestion(
            query_title=query,
            query_year=year,
            tmdb_id=movie_id,
            title=title,
            original_title=original_title,
            release_year=release_year,
            overview=str(details.get("overview") or "").strip(),
            tagline=str(details.get("tagline") or "").strip(),
            release_date=str(
                details.get("release_date") or selected.get("release_date") or ""
            ).strip(),
            runtime_min=_int_or_none(details.get("runtime")),
            vote_average=_float_or_none(details.get("vote_average")),
            certification=_certification_from_release_dates(details),
            imdb_id=str(
                (details.get("external_ids") or {}).get("imdb_id")
                or details.get("imdb_id")
                or ""
            ).strip(),
            countries=tuple(
                _names_from_dicts(details.get("production_countries"), key="name")
            ),
            genres=tuple(_names_from_dicts(details.get("genres"), key="name")),
            studios=tuple(
                _names_from_dicts(details.get("production_companies"), key="name")
            ),
            tags=tuple(_movie_tags(details)),
            directors=tuple(_credit_names(details.get("credits"), {"Director"})),
            writers=tuple(
                _credit_names(details.get("credits"), {"Writer", "Screenplay", "Story"})
            ),
            actors=tuple(_actors_from_credits(details.get("credits"), limit=20)),
            trailer_url=_trailer_url(details),
            collection_id=collection_id,
            collection_name=collection_name,
            collection_part_count=part_count,
            provider="tmdb",
            provider_id=movie_id,
        )

    def resolve_series(
        self,
        query: str,
        *,
        year: int | None = None,
    ) -> SeriesMetadataSuggestion | None:
        results = self._search_tv_with_title_variants(query, year=year)
        if not results:
            return None

        selected = self._select_best_result(results, year, date_key="first_air_date")
        if not selected:
            return None

        tv_id = int(selected["id"])
        details = self.tv_details(tv_id)
        name = str(details.get("name") or selected.get("name") or query).strip()
        original_name = str(
            details.get("original_name") or selected.get("original_name") or name
        ).strip()
        first_air_year = (
            _year_from_date(
                details.get("first_air_date") or selected.get("first_air_date")
            )
            or year
        )

        return SeriesMetadataSuggestion(
            query_title=query,
            query_year=year,
            tmdb_id=tv_id,
            name=name,
            original_name=original_name,
            first_air_year=first_air_year,
            overview=str(details.get("overview") or "").strip(),
            first_air_date=str(
                details.get("first_air_date") or selected.get("first_air_date") or ""
            ).strip(),
            provider="tmdb",
            provider_id=tv_id,
        )

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
        season = int(parsed.get("season") or 0)
        episode = int(parsed.get("episode") or 0)
        if season < 0 or episode <= 0:
            return None
        details = self.tv_episode_details(
            series.tmdb_id,
            season,
            episode,
            append_to_response="credits,external_ids",
        )
        title, title_is_fallback = normalize_episode_metadata_title(
            details.get("name"), episode, source_path=path
        )
        credits = details.get("credits") or {}
        episode_id = int(details.get("id") or 0)
        return EpisodeMetadataSuggestion(
            query_series=str(parsed["series"]),
            series_tmdb_id=series.tmdb_id,
            episode_tmdb_id=episode_id,
            show_name=series.name,
            original_show_name=series.original_name,
            season_number=season,
            episode_number=episode,
            title=title,
            overview=str(details.get("overview") or "").strip(),
            air_date=str(details.get("air_date") or "").strip(),
            runtime_min=_int_or_none(details.get("runtime")),
            vote_average=_float_or_none(details.get("vote_average")),
            imdb_id=str((details.get("external_ids") or {}).get("imdb_id") or "").strip(),
            directors=tuple(_credit_names(credits, {"Director"})),
            writers=tuple(
                _credit_names(credits, {"Writer", "Screenplay", "Story", "Teleplay"})
            ),
            actors=tuple(_actors_from_credits(credits, limit=20)),
            provider="tmdb",
            series_provider_id=series.tmdb_id,
            episode_provider_id=episode_id,
            title_is_fallback=title_is_fallback,
        )

    def clear_cache(self) -> int:
        return _clear_cache_dir(self.cache_dir)

    def _select_best_result(
        self,
        results: list[dict[str, Any]],
        year: int | None,
        *,
        date_key: str,
    ) -> dict[str, Any] | None:
        if not results:
            return None
        if year:
            for result in results:
                if _year_from_date(result.get(date_key)) == year:
                    return result
        return results[0]

    def _search_movies_with_title_variants(
        self,
        query: str,
        *,
        year: int | None = None,
    ) -> list[dict[str, Any]]:
        for variant in german_umlaut_search_variants(query) or (query,):
            results = self.search_movies(variant, year=year)
            if results:
                return results
            if self.config.fallback_language != self.config.language:
                results = self.search_movies(
                    variant,
                    year=year,
                    language=self.config.fallback_language,
                )
                if results:
                    return results
        return []

    def _search_tv_with_title_variants(
        self,
        query: str,
        *,
        year: int | None = None,
    ) -> list[dict[str, Any]]:
        for variant in german_umlaut_search_variants(query) or (query,):
            results = self.search_tv(variant, year=year)
            if results:
                return results
            if self.config.fallback_language != self.config.language:
                results = self.search_tv(
                    variant,
                    year=year,
                    language=self.config.fallback_language,
                )
                if results:
                    return results
        return []
