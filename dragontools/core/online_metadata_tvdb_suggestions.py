# -*- coding: utf-8 -*-
from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from .online_metadata_common import (
    MovieMetadataSuggestion,
    OnlineMetadataError,
    SeriesMetadataSuggestion,
    _float_or_none,
    _int_or_none,
    _year_from_date,
    compare_metadata_text,
)
from .online_metadata_tvdb_helpers import (
    _single_record_from_data,
    _tvdb_localized_title,
    _tvdb_record_id,
    _tvdb_remote_id,
    _tvdb_text,
    _year_from_tvdb_record,
)

class TvdbSuggestionMixin:
    def _movie_suggestion_from_record(
        self,
        query: str,
        year: int | None,
        record: dict[str, Any],
    ) -> MovieMetadataSuggestion | None:
        movie_id = _tvdb_record_id(record)
        if movie_id is None:
            return None
        try:
            details_payload = self.movie_details(movie_id, include_translations=True)
            details = _single_record_from_data(details_payload) or record
        except OnlineMetadataError:
            details = record
        title = (
            _tvdb_localized_title(details, self.config.language)
            or _tvdb_localized_title(details, self.config.fallback_language)
            or _tvdb_localized_title(record, self.config.language)
            or _tvdb_localized_title(record, self.config.fallback_language)
            or _tvdb_text(record, "name_translated", "title", "name")
            or _tvdb_text(details, "name_translated", "title", "name")
        )
        original_title = _tvdb_text(
            details,
            "originalName",
            "original_name",
            "originalTitle",
            "original_title",
            "name",
        ) or title
        release_date = str(
            details.get("first_release")
            or details.get("firstRelease")
            or details.get("releaseDate")
            or record.get("first_release")
            or record.get("releaseDate")
            or record.get("year")
            or ""
        ).strip()
        release_year = _year_from_date(release_date) or _year_from_tvdb_record(record) or year
        return MovieMetadataSuggestion(
            query_title=query,
            query_year=year,
            tmdb_id=movie_id,
            title=title or query,
            original_title=original_title or title or query,
            release_year=release_year,
            overview=_tvdb_text(details, "overview", "overview_translated"),
            release_date=release_date,
            runtime_min=_int_or_none(details.get("runtime") or details.get("runtime_min")),
            vote_average=_float_or_none(details.get("score")),
            imdb_id=_tvdb_remote_id(details, "imdb") or _tvdb_remote_id(record, "imdb"),
            provider="thetvdb",
            provider_id=movie_id,
        )

    def _series_suggestion_from_record(
        self,
        query: str,
        year: int | None,
        record: dict[str, Any],
    ) -> SeriesMetadataSuggestion | None:
        series_id = _int_or_none(record.get("tvdb_id") or record.get("id") or record.get("seriesId"))
        if series_id is None:
            return None
        try:
            details_payload = self.series_details(series_id, include_translations=True)
            details = _single_record_from_data(details_payload) or record
        except OnlineMetadataError:
            details = record
        name = (
            _tvdb_localized_title(details, self.config.language)
            or _tvdb_localized_title(details, self.config.fallback_language)
            or _tvdb_localized_title(record, self.config.language)
            or _tvdb_localized_title(record, self.config.fallback_language)
            or _tvdb_text(record, "name_translated", "name")
            or _tvdb_text(details, "name_translated", "name", "slug")
        )
        original_name = _tvdb_text(details, "originalName", "original_name", "name") or name
        first_air_date = str(
            details.get("firstAired")
            or details.get("first_air_date")
            or record.get("firstAired")
            or record.get("year")
            or ""
        ).strip()
        first_air_year = _year_from_date(first_air_date) or _year_from_tvdb_record(record) or year
        return SeriesMetadataSuggestion(
            query_title=query,
            query_year=year,
            tmdb_id=series_id,
            name=name or query,
            original_name=original_name or name or query,
            first_air_year=first_air_year,
            overview=_tvdb_text(details, "overview", "overview_translated"),
            first_air_date=first_air_date,
            provider="thetvdb",
            provider_id=series_id,
        )

    def _select_best_result(
        self,
        results: list[dict[str, Any]],
        query: str,
        year: int | None,
    ) -> dict[str, Any] | None:
        if not results:
            return None
        if year:
            for result in results:
                if _year_from_tvdb_record(result) == year:
                    return result
        query_norm = compare_metadata_text(query)
        return max(
            results,
            key=lambda item: (
                SequenceMatcher(
                    None,
                    query_norm,
                    compare_metadata_text(
                        _tvdb_localized_title(item, self.config.language)
                        or _tvdb_localized_title(item, self.config.fallback_language)
                        or _tvdb_text(item, "name_translated", "name")
                    ),
                ).ratio(),
                float(item.get("score") or 0),
            ),
        )

    def _find_episode(self, episodes: list[dict[str, Any]], season: int, episode: int) -> dict[str, Any] | None:
        for item in episodes:
            # Staffel 0 ist ein gueltiger Wert (Specials), darf also nicht durch
            # eine ``or``-Kette wie ein fehlender Wert behandelt werden.
            season_value = next(
                (
                    item.get(key)
                    for key in (
                        "seasonNumber",
                        "season_number",
                        "airedSeason",
                        "officialSeasonNumber",
                    )
                    if item.get(key) is not None
                ),
                None,
            )
            s = _int_or_none(season_value)
            e = _int_or_none(
                item.get("number")
                or item.get("episodeNumber")
                or item.get("episode_number")
                or item.get("airedEpisodeNumber")
                or item.get("officialEpisodeNumber")
            )
            if s == season and e == episode:
                return item
        return None
