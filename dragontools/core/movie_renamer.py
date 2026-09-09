# -*- coding: utf-8 -*-
"""Compatibility facade and orchestration for file renaming.

Parsing, models, and metadata candidate scoring are intentionally separated so
this module only coordinates the rename proposal workflow. Existing imports
from ``dragontools.core.movie_renamer`` remain stable.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from .movie_renamer_models import (
    MovieRenameCandidate,
    MovieRenameProposal,
    MovieSearchResolver,
    ParsedMovieReleaseName,
    ParsedSeriesReleaseName,
    RenameProposal,
    SeriesRenameCandidate,
    SeriesRenameProposal,
    SeriesSearchResolver,
)
from .movie_renamer_parsing import (
    EDITION_PATTERNS,
    TECHNICAL_TAG_PATTERNS,
    VIDEO_SUFFIXES,
    build_series_target_filename,
    build_target_filename,
    parse_movie_release_name,
    parse_series_release_name,
    release_style_warnings,
    rename_movie_file,
    sanitize_filename_part,
)
from .movie_renamer_candidates import (
    _candidate_from_result,
    _limit_candidates_with_provider_coverage,
    _resolve_raw_results,
    _resolve_series_results,
    _series_candidate_from_result as _candidate_series_from_result,
)
from .online_metadata_common import default_episode_title
from .paths import path_compare_key
from ..rules.renamer_rules import (
    apply_title_exception,
    manual_review_below,
    minimum_candidate_score,
)


def _series_candidate_from_result(raw: Any, parsed: ParsedSeriesReleaseName) -> SeriesRenameCandidate | None:
    """Compatibility wrapper that preserves monkeypatchable alias rules."""
    return _candidate_series_from_result(raw, parsed, title_exception=apply_title_exception)

def build_movie_rename_proposal(
    path: str | Path,
    *,
    resolver: MovieSearchResolver | None = None,
    client: Any | None = None,
    limit: int = 6,
) -> MovieRenameProposal:
    source_path = Path(path)
    parsed = parse_movie_release_name(source_path)
    warnings = list(parsed.warnings)
    candidates: list[MovieRenameCandidate] = []
    if parsed.is_probable_series:
        return MovieRenameProposal(
            source_path=source_path,
            parsed=parsed,
            status="not_movie",
            warnings=tuple(warnings),
        )

    try:
        raw_results = _resolve_raw_results(parsed.query_title, parsed.year, resolver=resolver, client=client)
        for raw in raw_results:
            candidate = _candidate_from_result(raw, parsed.query_title, parsed.year)
            if candidate and candidate.title:
                candidates.append(candidate)
    except Exception as exc:
        warnings.append(f"Metadaten-Suche fehlgeschlagen: {exc}")

    candidates = [item for item in candidates if item.score >= minimum_candidate_score()]
    candidates = _limit_candidates_with_provider_coverage(candidates, client=client, limit=limit)
    selected = candidates[0] if candidates else None
    if not selected:
        return MovieRenameProposal(
            source_path=source_path,
            parsed=parsed,
            candidates=tuple(candidates),
            status="no_match",
            warnings=tuple(warnings + ["Kein passender Metadaten-Treffer gefunden."]),
        )

    target_name = build_target_filename(selected.title, selected.year or parsed.year, parsed.suffix)
    target_path = source_path.with_name(target_name)
    target_exists = target_path.exists() and path_compare_key(target_path) != path_compare_key(source_path)
    status = "ok"
    if target_exists:
        status = "conflict"
        warnings.append("Zieldatei existiert bereits.")
    elif selected.score < manual_review_below():
        status = "manual_review"
        warnings.append("Treffer ist unsicher und sollte manuell geprüft werden.")

    return MovieRenameProposal(
        source_path=source_path,
        parsed=parsed,
        candidates=tuple(candidates),
        selected=selected,
        target_name=target_name,
        target_path=target_path,
        status=status,
        confidence=selected.score,
        warnings=tuple(warnings),
        target_exists=target_exists,
    )


def build_series_rename_proposal(
    path: str | Path,
    *,
    resolver: SeriesSearchResolver | None = None,
    client: Any | None = None,
    limit: int = 6,
    query_override: str | None = None,
) -> SeriesRenameProposal:
    source_path = Path(path)
    parsed = parse_series_release_name(source_path)
    if parsed is None:
        fallback = parse_movie_release_name(source_path)
        empty = ParsedSeriesReleaseName(
            source_name=fallback.source_name,
            suffix=fallback.suffix,
            series=fallback.query_title,
            season=0,
            episode=0,
            year=fallback.year,
            warnings=tuple(fallback.warnings + ("Kein Serienmuster erkannt.",)),
        )
        return SeriesRenameProposal(source_path=source_path, parsed=empty, status="not_series", warnings=empty.warnings)

    warnings = list(parsed.warnings)
    manual_query = str(query_override or "").strip()
    if manual_query:
        parsed = replace(parsed, series=manual_query)
        warnings.append(f"Manuelle Seriensuche: {manual_query}")
    candidates: list[SeriesRenameCandidate] = []
    try:
        raw_results = _resolve_series_results(parsed, resolver=resolver, client=client)
        for raw in raw_results:
            candidate = _series_candidate_from_result(raw, parsed)
            if candidate and candidate.series:
                candidates.append(candidate)
    except Exception as exc:
        warnings.append(f"Serien-Metadatensuche fehlgeschlagen: {exc}")

    candidates = [item for item in candidates if item.score >= minimum_candidate_score()]
    candidates = _limit_candidates_with_provider_coverage(candidates, client=client, limit=limit)
    selected = candidates[0] if candidates else None
    if selected is None:
        target_name = build_series_target_filename(
            parsed.series,
            parsed.season,
            parsed.episode,
            default_episode_title(parsed.episode),
            parsed.suffix,
        )
        target_path = source_path.with_name(target_name)
        return SeriesRenameProposal(
            source_path=source_path,
            parsed=parsed,
            target_name=target_name,
            target_path=target_path,
            status="no_match",
            warnings=tuple(warnings + ["Kein passender Serien-/Episodentreffer gefunden."]),
        )

    target_name = build_series_target_filename(
        selected.series,
        selected.season,
        selected.episode,
        selected.episode_title or default_episode_title(selected.episode),
        parsed.suffix,
    )
    target_path = source_path.with_name(target_name)
    target_exists = target_path.exists() and path_compare_key(target_path) != path_compare_key(source_path)
    status = "ok"
    if target_exists:
        status = "conflict"
        warnings.append("Zieldatei existiert bereits.")
    elif selected.score < manual_review_below():
        status = "manual_review"
        warnings.append("Treffer ist unsicher und sollte manuell geprüft werden.")

    return SeriesRenameProposal(
        source_path=source_path,
        parsed=parsed,
        candidates=tuple(candidates),
        selected=selected,
        target_name=target_name,
        target_path=target_path,
        status=status,
        confidence=selected.score,
        warnings=tuple(warnings),
        target_exists=target_exists,
    )


def build_rename_proposal(
    path: str | Path,
    *,
    movie_client: Any | None = None,
    series_client: Any | None = None,
    movie_resolver: MovieSearchResolver | None = None,
    series_resolver: SeriesSearchResolver | None = None,
    limit: int = 6,
    series_query_override: str | None = None,
) -> RenameProposal:
    parsed = parse_movie_release_name(path)
    if parsed.is_probable_series:
        return build_series_rename_proposal(
            path,
            resolver=series_resolver,
            client=series_client,
            limit=limit,
            query_override=series_query_override,
        )
    return build_movie_rename_proposal(
        path,
        resolver=movie_resolver,
        client=movie_client,
        limit=limit,
    )


__all__ = [
    "EDITION_PATTERNS",
    "MovieRenameCandidate",
    "MovieRenameProposal",
    "MovieSearchResolver",
    "ParsedMovieReleaseName",
    "ParsedSeriesReleaseName",
    "RenameProposal",
    "SeriesRenameCandidate",
    "SeriesRenameProposal",
    "SeriesSearchResolver",
    "TECHNICAL_TAG_PATTERNS",
    "VIDEO_SUFFIXES",
    "build_movie_rename_proposal",
    "build_rename_proposal",
    "build_series_rename_proposal",
    "build_series_target_filename",
    "build_target_filename",
    "parse_movie_release_name",
    "parse_series_release_name",
    "release_style_warnings",
    "rename_movie_file",
    "sanitize_filename_part",
]
