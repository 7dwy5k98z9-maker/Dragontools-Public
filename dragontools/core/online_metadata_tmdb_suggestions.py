# -*- coding: utf-8 -*-
from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .online_metadata_common import (
    EpisodeMetadataSuggestion,
    OnlineMetadataError,
    _actors_from_credits,
    _credit_names,
    _float_or_none,
    _int_or_none,
    _year_from_date,
    compare_metadata_text,
    normalize_episode_metadata_title,
    parse_series_query,
)


class TmdbSuggestionMixin:
    """Candidate discovery and ranking for episode metadata suggestions."""

    def resolve_episode_candidates(
        self,
        path: str | Path,
        *,
        limit: int = 6,
    ) -> tuple[EpisodeMetadataSuggestion, ...]:
        try:
            from ..rules.move_rules import parse_series_match_details
            from ..rules.renamer_rules import (
                minimum_candidate_score,
                retry_without_year_enabled,
                series_search_queries,
            )
        except Exception:
            return ()

        parsed = parse_series_match_details(Path(path).name)
        if not parsed or not parsed.get("series"):
            return ()

        series_query = parse_series_query(Path(path).name)
        query = (series_query.title or str(parsed["series"])).strip()
        season = int(parsed.get("season") or 0)
        episode = int(parsed.get("episode") or 0)
        if not query or season < 0 or episode <= 0:
            return ()

        records = self._collect_episode_candidate_records(
            query,
            year=series_query.year,
            search_terms=series_search_queries(query),
            retry_without_year=retry_without_year_enabled(),
        )
        if not records:
            return ()

        query_norm = compare_metadata_text(query)
        ordered = sorted(
            records,
            key=lambda record: self._episode_candidate_rank(
                record,
                query_norm=query_norm,
                query_year=series_query.year,
            ),
            reverse=True,
        )
        title_floor = max(0.35, minimum_candidate_score() - 0.20)
        cap = max(1, int(limit))
        suggestions: list[EpisodeMetadataSuggestion] = []

        for record in ordered:
            rank_score = self._episode_candidate_rank(
                record,
                query_norm=query_norm,
                query_year=series_query.year,
            )[0]
            if rank_score < title_floor:
                continue
            suggestion = self._episode_suggestion_from_candidate(
                record,
                path=path,
                query=query,
                query_year=series_query.year,
                season=season,
                episode=episode,
            )
            if suggestion is None:
                continue
            suggestions.append(suggestion)
            if len(suggestions) >= cap:
                break

        return tuple(suggestions)

    def _collect_episode_candidate_records(
        self,
        query: str,
        *,
        year: int | None,
        search_terms: list[str] | tuple[str, ...],
        retry_without_year: bool,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        seen_ids: set[int] = set()
        exact_terms = search_terms[:2]
        fuzzy_terms = search_terms[2:]

        def collect(term: str, search_year: int | None) -> None:
            try:
                found = self.search_tv(term, year=search_year)
                if not found and self.config.fallback_language != self.config.language:
                    found = self.search_tv(
                        term,
                        year=search_year,
                        language=self.config.fallback_language,
                    )
            except OnlineMetadataError:
                found = []
            for record in found or []:
                record_id = _int_or_none(record.get("id"))
                if record_id is None or record_id in seen_ids:
                    continue
                seen_ids.add(record_id)
                records.append(record)

        for term in exact_terms:
            collect(term, year)
            if year is not None and retry_without_year:
                collect(term, None)
        for term in fuzzy_terms:
            collect(term, None)
        return records

    @staticmethod
    def _episode_candidate_rank(
        record: dict[str, Any],
        *,
        query_norm: str,
        query_year: int | None,
    ) -> tuple[float, int, float]:
        title = str(record.get("name") or "").strip()
        original = str(record.get("original_name") or "").strip()
        title_score = max(
            SequenceMatcher(None, query_norm, compare_metadata_text(title)).ratio(),
            SequenceMatcher(None, query_norm, compare_metadata_text(original)).ratio(),
        )
        candidate_year = _year_from_date(record.get("first_air_date"))
        year_score = int(
            query_year is not None
            and candidate_year is not None
            and int(query_year) == int(candidate_year)
        )
        return (title_score, year_score, float(record.get("popularity") or 0.0))

    def _episode_suggestion_from_candidate(
        self,
        record: dict[str, Any],
        *,
        path: str | Path,
        query: str,
        query_year: int | None,
        season: int,
        episode: int,
    ) -> EpisodeMetadataSuggestion | None:
        tv_id = _int_or_none(record.get("id"))
        if tv_id is None:
            return None
        try:
            details = self.tv_episode_details(
                tv_id,
                season,
                episode,
                append_to_response="credits,external_ids",
            )
        except OnlineMetadataError:
            return None

        episode_id = _int_or_none(details.get("id"))
        if episode_id is None:
            return None
        show_name = str(record.get("name") or query).strip() or query
        original_show_name = (
            str(record.get("original_name") or show_name).strip() or show_name
        )
        first_air_year = _year_from_date(record.get("first_air_date")) or query_year
        title, title_is_fallback = normalize_episode_metadata_title(
            details.get("name"),
            episode,
            source_path=path,
        )
        credits = details.get("credits") or {}

        return EpisodeMetadataSuggestion(
            query_series=query,
            series_tmdb_id=tv_id,
            episode_tmdb_id=episode_id,
            show_name=show_name,
            original_show_name=original_show_name,
            season_number=season,
            episode_number=episode,
            title=title,
            first_air_year=first_air_year,
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
            series_provider_id=tv_id,
            episode_provider_id=episode_id,
            title_is_fallback=title_is_fallback,
        )
