# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from difflib import SequenceMatcher
from typing import Any

from .online_metadata_identity import validate_tmdb_episode, provider_id
from .german_title_variants import german_umlaut_search_variants
from .online_metadata_common import (
    EpisodeMetadataSuggestion,
    MovieMetadataSuggestion,
    OnlineMetadataError,
    OnlineMetadataNotFoundError,
    OnlineMetadataResponseError,
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
    compare_metadata_text,
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
        results = self._tmdb_search_results(data, label="Film")
        if year is not None:
            results = [
                item for item in results
                if (candidate_year := _year_from_date(item.get("release_date"))) is None
                or candidate_year == int(year)
            ]
        return results

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
        results = self._tmdb_search_results(data, label="Serie")
        if year is not None:
            results = [
                item for item in results
                if (candidate_year := _year_from_date(item.get("first_air_date"))) is None
                or candidate_year == int(year)
            ]
        return results

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
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"language": language or self.config.language}
        if append_to_response:
            params["append_to_response"] = append_to_response
        return self._request_json(
            f"/tv/{int(tv_id)}/season/{int(season)}/episode/{int(episode)}",
            params,
            force_refresh=force_refresh,
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

        selected = self._select_best_result(results, query, year, date_key="release_date")
        if not selected:
            return None

        movie_id = int(selected["id"])
        try:
            details = self.movie_details(
                movie_id,
                append_to_response="credits,videos,keywords,release_dates,external_ids",
            )
        except OnlineMetadataNotFoundError:
            return None
        self._validate_detail_identity(details, movie_id, label="Film")
        if not self._title_match_is_plausible(
            query,
            details.get("title"), details.get("original_title"),
            selected.get("title"), selected.get("original_title"),
        ):
            return None
        title = str(details.get("title") or selected.get("title") or query).strip()
        original_title = str(
            details.get("original_title") or selected.get("original_title") or title
        ).strip()
        release_year = _year_from_date(
            details.get("release_date") or selected.get("release_date")
        )
        if year is not None and release_year != int(year):
            return None
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

        selected = self._select_best_result(results, query, year, date_key="first_air_date")
        if not selected:
            return None

        tv_id = int(selected["id"])
        try:
            details = self.tv_details(tv_id)
        except OnlineMetadataNotFoundError:
            return None
        self._validate_detail_identity(details, tv_id, label="Serie")
        if not self._title_match_is_plausible(
            query,
            details.get("name"), details.get("original_name"),
            selected.get("name"), selected.get("original_name"),
        ):
            return None
        name = str(details.get("name") or selected.get("name") or query).strip()
        original_name = str(
            details.get("original_name") or selected.get("original_name") or name
        ).strip()
        first_air_year = _year_from_date(
            details.get("first_air_date") or selected.get("first_air_date")
        )
        if year is not None and first_air_year != int(year):
            return None

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
        try:
            details = self.tv_episode_details(
                series.tmdb_id,
                season,
                episode,
                append_to_response="credits,external_ids",
            )
        except OnlineMetadataNotFoundError:
            return None
        validate_tmdb_episode(details, season, episode)
        title, title_is_fallback = normalize_episode_metadata_title(
            details.get("name"), episode, source_path=path
        )
        credits = details.get("credits") or {}
        episode_id = _int_or_none(details.get("id"))
        if episode_id is None:
            raise OnlineMetadataResponseError(
                "TMDB-Episodenantwort enthält keine gültige ID."
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
            first_air_year=series.first_air_year,
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
        self.enable_fresh_session()
        return _clear_cache_dir(self.cache_dir)

    @staticmethod
    def _tmdb_search_results(data: dict[str, Any], *, label: str) -> list[dict[str, Any]]:
        raw = data.get("results")
        if not isinstance(raw, list):
            raise OnlineMetadataResponseError(
                f"TMDB-{label}suche enthält keine gültige Ergebnisliste."
            )
        results: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            if provider_id(item.get("id")) is None:
                continue
            record = dict(item)
            record["provider"] = "tmdb"
            record["provider_id"] = int(item["id"])
            results.append(record)
        return results

    @staticmethod
    def _validate_detail_identity(details: dict[str, Any], expected_id: int, *, label: str) -> None:
        actual = provider_id(details.get("id"))
        if actual is not None and actual != int(expected_id):
            raise OnlineMetadataResponseError(
                f"TMDB-{label}details gehören zu ID {actual}, erwartet war {expected_id}."
            )

    def _select_best_result(
        self,
        results: list[dict[str, Any]],
        query: str,
        year: int | None,
        *,
        date_key: str,
    ) -> dict[str, Any] | None:
        eligible = [dict(item) for item in results if provider_id(item.get("id")) is not None]
        if year is not None:
            eligible = [
                item for item in eligible
                if (candidate_year := _year_from_date(item.get(date_key))) is None
                or candidate_year == int(year)
            ]
        if not eligible:
            return None

        query_key = compare_metadata_text(query)

        def score(item: dict[str, Any]) -> tuple[float, int, float]:
            names = (
                item.get("title"), item.get("name"),
                item.get("original_title"), item.get("original_name"),
            )
            title_score = max(
                (SequenceMatcher(None, query_key, compare_metadata_text(str(name))).ratio()
                 for name in names if str(name or "").strip()),
                default=0.0,
            )
            candidate_year = _year_from_date(item.get(date_key))
            year_score = int(year is not None and candidate_year == int(year))
            return title_score, year_score, float(item.get("popularity") or 0.0)

        return max(eligible, key=score)

    @staticmethod
    def _title_match_is_plausible(query: str, *names: Any) -> bool:
        query_key = compare_metadata_text(query)
        score = max(
            (SequenceMatcher(None, query_key, compare_metadata_text(str(name))).ratio()
             for name in names if str(name or "").strip()),
            default=0.0,
        )
        try:
            from ..rules.renamer_rules import minimum_candidate_score
            floor = float(minimum_candidate_score())
        except Exception:
            floor = 0.60
        return bool(query_key) and score >= floor

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
