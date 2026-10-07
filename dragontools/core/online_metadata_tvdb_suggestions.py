# -*- coding: utf-8 -*-
from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from .online_metadata_identity import episode_number, TVDB_SEASON_FIELDS, TVDB_EPISODE_FIELDS
from .online_metadata_common import (
    MovieMetadataSuggestion,
    OnlineMetadataError,
    OnlineMetadataNotFoundError,
    OnlineMetadataResponseError,
    SeriesMetadataSuggestion,
    _float_or_none,
    _int_or_none,
    _year_from_date,
    compare_metadata_text,
)
from .online_metadata_tvdb_helpers import (
    _single_record_from_data,
    _tvdb_localized_title,
    _tvdb_localized_overview,
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
        except OnlineMetadataNotFoundError:
            return None
        detail_id = _tvdb_record_id(details)
        if detail_id is None or detail_id != movie_id:
            raise OnlineMetadataResponseError(
                f"TheTVDB-Filmdetails gehören zu ID {detail_id}, erwartet war {movie_id}."
            )
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
        if not self._title_match_is_plausible(query, title, original_title):
            return None
        release_date, release_year = _movie_release_identity(details, record)
        if year is not None and release_year != int(year):
            return None
        return MovieMetadataSuggestion(
            query_title=query,
            query_year=year,
            tmdb_id=movie_id,
            title=title or query,
            original_title=original_title or title or query,
            release_year=release_year,
            overview=_tvdb_localized_overview(details, self.config.language)
            or _tvdb_localized_overview(details, self.config.fallback_language)
            or _tvdb_text(details, "overview"),
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
        *,
        force_refresh: bool = False,
    ) -> SeriesMetadataSuggestion | None:
        series_id = _tvdb_record_id(record)
        if series_id is None:
            return None
        try:
            details_payload = self.series_details(
                series_id, include_translations=True, force_refresh=force_refresh
            )
            details = _single_record_from_data(details_payload) or record
        except OnlineMetadataNotFoundError:
            return None
        detail_id = _tvdb_record_id(details)
        if detail_id is None or detail_id != series_id:
            raise OnlineMetadataResponseError(
                f"TheTVDB-Seriendetails gehören zu ID {detail_id}, erwartet war {series_id}."
            )
        name = (
            _tvdb_localized_title(details, self.config.language)
            or _tvdb_localized_title(details, self.config.fallback_language)
            or _tvdb_localized_title(record, self.config.language)
            or _tvdb_localized_title(record, self.config.fallback_language)
            or _tvdb_text(record, "name_translated", "name")
            or _tvdb_text(details, "name_translated", "name", "slug")
        )
        original_name = _tvdb_text(details, "originalName", "original_name", "name") or name
        if not self._title_match_is_plausible(query, name, original_name):
            return None
        first_air_date = str(
            details.get("firstAired")
            or details.get("first_air_date")
            or record.get("firstAired")
            or record.get("year")
            or ""
        ).strip()
        first_air_year = _year_from_date(first_air_date) or _year_from_tvdb_record(record)
        if year is not None and first_air_year != int(year):
            return None
        return SeriesMetadataSuggestion(
            query_title=query,
            query_year=year,
            tmdb_id=series_id,
            name=name or query,
            original_name=original_name or name or query,
            first_air_year=first_air_year,
            overview=_tvdb_localized_overview(details, self.config.language)
            or _tvdb_localized_overview(details, self.config.fallback_language)
            or _tvdb_text(details, "overview"),
            first_air_date=first_air_date,
            provider="thetvdb",
            provider_id=series_id,
        )

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

    def _select_best_result(
        self,
        results: list[dict[str, Any]],
        query: str,
        year: int | None,
    ) -> dict[str, Any] | None:
        if not results:
            return None
        eligible = [dict(item) for item in results if _tvdb_record_id(item) is not None]
        if year is not None:
            eligible = [
                item for item in eligible
                if (candidate_year := _year_from_tvdb_record(item)) is None
                or candidate_year == int(year)
            ]
        if not eligible:
            return None
        query_norm = compare_metadata_text(query)

        def score(item: dict[str, Any]) -> tuple[float, int, float]:
            names = (
                _tvdb_localized_title(item, self.config.language),
                _tvdb_localized_title(item, self.config.fallback_language),
                _tvdb_text(item, "name_translated", "name"),
                _tvdb_text(item, "originalName", "original_name", "originalTitle", "original_title"),
            )
            title_score = max(
                (SequenceMatcher(None, query_norm, compare_metadata_text(name)).ratio()
                 for name in names if str(name or "").strip()),
                default=0.0,
            )
            return (
                title_score,
                int(year is not None and _year_from_tvdb_record(item) == int(year)),
                float(item.get("score") or 0),
            )

        return max(eligible, key=score)

    def _find_episode(self, episodes, season, episode):
        for item in episodes:
            actual_season = episode_number(item, TVDB_SEASON_FIELDS, minimum=0)
            actual_episode = episode_number(item, TVDB_EPISODE_FIELDS)
            if actual_season == season and actual_episode == episode:
                return item
        return None


def _movie_release_identity(details, record):
    keys = ('first_release', 'firstRelease', 'releaseDate')
    release_date = next((details.get(key) for key in keys if details.get(key)), None)
    if not release_date:
        release_date = next((record.get(key) for key in ('first_release', 'releaseDate', 'year') if record.get(key)), '')
    date = str(release_date).strip()
    return date, _year_from_date(date) or _year_from_tvdb_record(record)
