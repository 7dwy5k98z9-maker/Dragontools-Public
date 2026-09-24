# -*- coding: utf-8 -*-
"""TMDB batch path used by the GUI renamer.

The normal metadata pipeline intentionally keeps the rich per-episode endpoint.
For mass-renaming we only need identity/title fields, so one season response can
serve all SxxExx files of that season.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .online_metadata_common import (
    EpisodeMetadataSuggestion,
    OnlineMetadataError,
    _float_or_none,
    _int_or_none,
    _year_from_date,
    compare_metadata_text,
    normalize_episode_metadata_title,
    parse_series_query,
)


class TmdbRenamerBatchMixin:
    def tv_season_details(
        self,
        tv_id: int,
        season: int,
        *,
        language: str | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Load one TMDB season once for renamer batch resolution."""
        lang = str(language or self.config.language)
        key = (int(tv_id), int(season), lang)
        cache = getattr(self, "_renamer_season_cache", None)
        lock = getattr(self, "_renamer_batch_lock", None)

        def cached() -> dict[str, Any] | None:
            if force_refresh or cache is None:
                return None
            value = cache.get(key)
            return dict(value) if isinstance(value, dict) else None

        if lock is None:
            existing = cached()
            if existing is not None:
                return existing
            payload = self._request_json(
                f"/tv/{int(tv_id)}/season/{int(season)}",
                {"language": lang},
                force_refresh=force_refresh,
            )
            if cache is not None:
                cache[key] = dict(payload)
            return dict(payload)

        with lock:
            existing = cached()
            if existing is not None:
                return existing
            payload = self._request_json(
                f"/tv/{int(tv_id)}/season/{int(season)}",
                {"language": lang},
                force_refresh=force_refresh,
            )
            if cache is not None:
                cache[key] = dict(payload)
            return dict(payload)

    def resolve_renamer_episode_candidates(
        self,
        path: str | Path,
        *,
        limit: int = 6,
    ) -> tuple[EpisodeMetadataSuggestion, ...]:
        try:
            from ..rules.move_rules import parse_series_match_details
            from ..rules.renamer_rules import (
                candidate_discovery_floor,
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
        title_floor = candidate_discovery_floor()
        cap = max(1, int(limit))
        suggestions: list[EpisodeMetadataSuggestion] = []
        for record in ordered:
            if self._episode_candidate_rank(
                record,
                query_norm=query_norm,
                query_year=series_query.year,
            )[0] < title_floor:
                continue
            suggestion = self._renamer_episode_suggestion_from_candidate(
                record,
                path=path,
                query=query,
                query_year=series_query.year,
                season=season,
                episode=episode,
            )
            if suggestion is not None:
                suggestions.append(suggestion)
            if len(suggestions) >= cap:
                break
        return tuple(suggestions)

    def _renamer_episode_suggestion_from_candidate(
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

        details = self._renamer_episode_from_season(tv_id, season, episode)
        if details is None and self.config.fallback_language != self.config.language:
            details = self._renamer_episode_from_season(
                tv_id,
                season,
                episode,
                language=self.config.fallback_language,
            )
        if details is None:
            # Keep old behaviour as a compatibility fallback for unusual TMDB
            # payloads or providers that do not expose the season endpoint.
            return self._episode_suggestion_from_candidate(
                record,
                path=path,
                query=query,
                query_year=query_year,
                season=season,
                episode=episode,
                force_refresh=False,
            )

        episode_id = _int_or_none(details.get("id"))
        if episode_id is None:
            return None
        title, title_is_fallback = normalize_episode_metadata_title(
            details.get("name"),
            episode,
            source_path=path,
        )
        if title_is_fallback:
            # Only incomplete provider data pays for a concrete episode refresh.
            # Normal mass-renamer runs stay at one request per season.
            try:
                refreshed = self.tv_episode_details(
                    tv_id,
                    season,
                    episode,
                    append_to_response="credits,external_ids",
                    force_refresh=True,
                )
            except OnlineMetadataError:
                refreshed = None
            if isinstance(refreshed, dict) and refreshed:
                details = refreshed
                episode_id = _int_or_none(details.get("id")) or episode_id
                title, title_is_fallback = normalize_episode_metadata_title(
                    details.get("name"),
                    episode,
                    source_path=path,
                )

        show_name = str(record.get("name") or query).strip() or query
        original_show_name = str(record.get("original_name") or show_name).strip() or show_name
        first_air_year = _year_from_date(record.get("first_air_date")) or query_year
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
            provider="tmdb",
            series_provider_id=tv_id,
            episode_provider_id=episode_id,
            title_is_fallback=title_is_fallback,
        )

    def _renamer_episode_from_season(
        self,
        tv_id: int,
        season: int,
        episode: int,
        *,
        language: str | None = None,
    ) -> dict[str, Any] | None:
        try:
            payload = self.tv_season_details(tv_id, season, language=language)
        except OnlineMetadataError:
            return None
        for item in payload.get("episodes") or []:
            if not isinstance(item, dict):
                continue
            number = _int_or_none(item.get("episode_number") or item.get("number"))
            if number == int(episode):
                return dict(item)
        return None


__all__ = ["TmdbRenamerBatchMixin"]
