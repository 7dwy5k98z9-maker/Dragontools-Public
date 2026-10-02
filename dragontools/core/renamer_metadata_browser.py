# -*- coding: utf-8 -*-
"""Provider-explicit metadata browser support for the Renamer.

The normal Renamer starts from filenames and tries to infer the matching title.
This module implements the inverse workflow used by the metadata browser:
select an exact TMDB/TheTVDB title first, then map local files to it.

The core intentionally has no Qt dependency.  The GUI can therefore be tested
separately and explicit mappings stay deterministic and race-free.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Literal, Sequence

from .movie_renamer_models import (
    MovieRenameCandidate,
    MovieRenameProposal,
    ParsedSeriesReleaseName,
    SeriesRenameCandidate,
    SeriesRenameProposal,
)
from .movie_renamer_parsing import (
    build_series_multi_target_filename,
    build_target_filename,
    parse_movie_release_name,
    parse_series_release_name,
)
from .online_metadata_config import config_from_settings
from .online_metadata_common import (
    OnlineMetadataAuthError,
    OnlineMetadataConfig,
    OnlineMetadataError,
    _int_or_none,
    _year_from_date,
    normalize_episode_metadata_title,
)
from .online_metadata_tmdb import TmdbClient
from .online_metadata_tvdb import TheTvdbClient
from .online_metadata_tvdb_helpers import (
    _tvdb_localized_title,
    _tvdb_record_id,
    _tvdb_text,
    _year_from_tvdb_record,
)
from .path_syntax import path_compare_key

MetadataKind = Literal["series", "movie"]
ProviderName = Literal["tmdb", "thetvdb"]
TitleMode = Literal["all", "first", "none"]


@dataclass(frozen=True, slots=True)
class MetadataBrowserHit:
    kind: MetadataKind
    provider: ProviderName
    provider_id: int
    title: str
    original_title: str = ""
    year: int | None = None
    overview: str = ""

    @property
    def provider_label(self) -> str:
        return "TheTVDB" if self.provider == "thetvdb" else "TMDB"

    @property
    def display_title(self) -> str:
        return f"{self.title} ({self.year})" if self.year else self.title


@dataclass(frozen=True, slots=True)
class MetadataBrowserEpisode:
    season: int
    episode: int
    title: str
    provider_episode_id: int | None = None
    air_date: str = ""

    @property
    def code(self) -> str:
        return f"S{self.season:02d}E{self.episode:02d}"


@dataclass(frozen=True, slots=True)
class ExplicitMovieFileMapping:
    source_path: Path
    hit: MetadataBrowserHit

    def __post_init__(self) -> None:
        if self.hit.kind != "movie":
            raise ValueError("Filmzuordnung benötigt einen Film-Treffer.")


@dataclass(frozen=True, slots=True)
class ExplicitSeriesFileMapping:
    source_path: Path
    hit: MetadataBrowserHit
    season: int
    episodes: tuple[MetadataBrowserEpisode, ...]
    title_mode: TitleMode = "all"

    def __post_init__(self) -> None:
        if self.hit.kind != "series":
            raise ValueError("Serienzuordnung benötigt einen Serien-Treffer.")
        if int(self.season) < 0:
            raise ValueError("Staffelnummern dürfen nicht negativ sein.")
        if self.title_mode not in {"all", "first", "none"}:
            raise ValueError(f"Unbekannter Mehrfachfolgen-Titelmodus: {self.title_mode!r}")
        if not self.episodes:
            raise ValueError("Eine Serienzuordnung benötigt mindestens eine Episode.")
        if len(self.episodes) > 4:
            raise ValueError("Pro Datei werden höchstens vier Episoden unterstützt.")
        seasons = {int(item.season) for item in self.episodes}
        if seasons != {int(self.season)}:
            raise ValueError("Mehrfachfolgen dürfen keine Staffelgrenze überschreiten.")
        numbers = tuple(int(item.episode) for item in self.episodes)
        if any(number <= 0 for number in numbers):
            raise ValueError("Episodennummern müssen größer als 0 sein.")
        if numbers != tuple(range(numbers[0], numbers[0] + len(numbers))):
            raise ValueError("Mehrfachfolgen müssen aus aufeinanderfolgenden Episoden bestehen.")


ExplicitFileMapping = ExplicitMovieFileMapping | ExplicitSeriesFileMapping


class RenamerMetadataBrowserService:
    """Small provider facade used by the metadata-browser dialog.

    Unlike the normal provider preference chain, the browser deliberately shows
    every *enabled and credentialed* provider side by side.  This is what lets a
    user compare TMDB and TheTVDB entries explicitly before mapping files.
    """

    def __init__(self, config: OnlineMetadataConfig) -> None:
        self.config = config
        clients: dict[str, Any] = {}
        if config.tmdb_enabled and config.has_tmdb_credentials:
            clients["tmdb"] = TmdbClient(config)
        if config.tvdb_enabled and config.has_tvdb_credentials:
            clients["thetvdb"] = TheTvdbClient(config)
        if not clients:
            raise OnlineMetadataAuthError(
                "Für den Metadaten-Browser ist weder TMDB noch TheTVDB vollständig eingerichtet."
            )
        self._clients = clients

    @classmethod
    def from_settings(cls, settings) -> "RenamerMetadataBrowserService":
        return cls(config_from_settings(settings, require_enabled=False))

    @property
    def providers(self) -> tuple[str, ...]:
        return tuple(self._clients)

    def search(self, query: str, *, kind: MetadataKind, limit_per_provider: int = 10) -> tuple[MetadataBrowserHit, ...]:
        text = str(query or "").strip()
        if not text:
            return ()
        cap = max(1, min(int(limit_per_provider), 25))
        hits: list[MetadataBrowserHit] = []
        errors: list[str] = []
        successful = 0
        for provider, client in self._clients.items():
            try:
                if kind == "series":
                    raw = client.search_tv(text) if provider == "tmdb" else client.search_series(text)
                else:
                    raw = client.search_movies(text)
            except OnlineMetadataError as exc:
                errors.append(f"{self._provider_label(provider)}: {exc}")
                continue
            successful += 1
            for record in list(raw or [])[:cap]:
                hit = self._hit_from_record(kind, provider, record)
                if hit is not None:
                    hits.append(hit)
        if successful == 0 and errors:
            raise OnlineMetadataError("Alle Metadaten-Provider sind fehlgeschlagen: " + "; ".join(errors))
        return tuple(hits)

    def series_seasons(self, hit: MetadataBrowserHit) -> tuple[int, ...]:
        self._require_kind(hit, "series")
        client = self._client(hit.provider)
        if hit.provider == "tmdb":
            payload = client.tv_details(hit.provider_id)
            seasons = {
                int(item.get("season_number"))
                for item in (payload.get("seasons") or [])
                if item.get("season_number") is not None
            }
        else:
            episodes = client.series_episodes(hit.provider_id, language=self.config.language)
            seasons = {
                number
                for item in episodes
                if (number := self._tvdb_season_number(item)) is not None
            }
        return tuple(sorted(number for number in seasons if number >= 0))

    def series_episodes(self, hit: MetadataBrowserHit, season: int) -> tuple[MetadataBrowserEpisode, ...]:
        self._require_kind(hit, "series")
        season = int(season)
        client = self._client(hit.provider)
        if hit.provider == "tmdb":
            return self._tmdb_season_episodes(client, hit, season)
        return self._tvdb_season_episodes(client, hit, season)

    def _tmdb_season_episodes(self, client, hit: MetadataBrowserHit, season: int) -> tuple[MetadataBrowserEpisode, ...]:
        payload = client.tv_season_details(hit.provider_id, season, language=self.config.language)
        primary = list(payload.get("episodes") or [])
        fallback_by_number: dict[int, dict[str, Any]] = {}
        if self.config.fallback_language and self.config.fallback_language != self.config.language:
            try:
                fallback = client.tv_season_details(
                    hit.provider_id, season, language=self.config.fallback_language
                )
                fallback_by_number = {
                    int(item.get("episode_number")): item
                    for item in (fallback.get("episodes") or [])
                    if item.get("episode_number") is not None
                }
            except OnlineMetadataError:
                fallback_by_number = {}

        result: list[MetadataBrowserEpisode] = []
        for item in primary:
            number = _int_or_none(item.get("episode_number"))
            if number is None or number <= 0:
                continue
            title, is_fallback = normalize_episode_metadata_title(item.get("name"), number)
            if is_fallback and number in fallback_by_number:
                fallback_title, fallback_is_generic = normalize_episode_metadata_title(
                    fallback_by_number[number].get("name"), number
                )
                if not fallback_is_generic:
                    title = fallback_title
            result.append(
                MetadataBrowserEpisode(
                    season=season,
                    episode=number,
                    title=title,
                    provider_episode_id=_int_or_none(item.get("id")),
                    air_date=str(item.get("air_date") or "").strip(),
                )
            )
        return tuple(sorted(result, key=lambda item: item.episode))

    def _tvdb_season_episodes(self, client, hit: MetadataBrowserHit, season: int) -> tuple[MetadataBrowserEpisode, ...]:
        primary = client.series_episodes(hit.provider_id, language=self.config.language)
        fallback_by_number: dict[int, dict[str, Any]] = {}
        if self.config.fallback_language and self.config.fallback_language != self.config.language:
            try:
                fallback = client.series_episodes(hit.provider_id, language=self.config.fallback_language)
                fallback_by_number = {
                    int(number): item
                    for item in fallback
                    if self._tvdb_season_number(item) == season
                    and (number := self._tvdb_episode_number(item)) is not None
                }
            except OnlineMetadataError:
                fallback_by_number = {}

        result: list[MetadataBrowserEpisode] = []
        for item in primary:
            if self._tvdb_season_number(item) != season:
                continue
            number = self._tvdb_episode_number(item)
            if number is None or number <= 0:
                continue
            raw_title = (
                _tvdb_localized_title(item, self.config.language)
                or _tvdb_text(item, "name_translated", "name", "title")
            )
            title, is_fallback = normalize_episode_metadata_title(raw_title, number)
            if is_fallback and number in fallback_by_number:
                fallback_item = fallback_by_number[number]
                fallback_title, fallback_is_generic = normalize_episode_metadata_title(
                    _tvdb_localized_title(fallback_item, self.config.fallback_language)
                    or _tvdb_text(fallback_item, "name_translated", "name", "title"),
                    number,
                )
                if not fallback_is_generic:
                    title = fallback_title
            result.append(
                MetadataBrowserEpisode(
                    season=season,
                    episode=number,
                    title=title,
                    provider_episode_id=_int_or_none(
                        item.get("id") or item.get("tvdb_id") or item.get("tvdbId") or item.get("episode_id")
                    ),
                    air_date=str(item.get("aired") or item.get("firstAired") or item.get("air_date") or "").strip(),
                )
            )
        return tuple(sorted(result, key=lambda item: item.episode))

    def _hit_from_record(self, kind: MetadataKind, provider: str, record: dict[str, Any]) -> MetadataBrowserHit | None:
        if provider == "tmdb":
            provider_id = _int_or_none(record.get("id"))
            if provider_id is None:
                return None
            if kind == "series":
                title = str(record.get("name") or record.get("original_name") or "").strip()
                original = str(record.get("original_name") or title).strip()
                year = _year_from_date(record.get("first_air_date"))
            else:
                title = str(record.get("title") or record.get("original_title") or "").strip()
                original = str(record.get("original_title") or title).strip()
                year = _year_from_date(record.get("release_date"))
            if not title:
                return None
            return MetadataBrowserHit(
                kind=kind,
                provider="tmdb",
                provider_id=provider_id,
                title=title,
                original_title=original,
                year=year,
                overview=str(record.get("overview") or "").strip(),
            )

        provider_id = _tvdb_record_id(record)
        if provider_id is None:
            return None
        title = (
            _tvdb_localized_title(record, self.config.language)
            or _tvdb_localized_title(record, self.config.fallback_language)
            or _tvdb_text(record, "name_translated", "name", "title")
        ).strip()
        if not title:
            return None
        original = _tvdb_text(
            record, "originalName", "original_name", "originalTitle", "original_title", "name"
        ) or title
        return MetadataBrowserHit(
            kind=kind,
            provider="thetvdb",
            provider_id=int(provider_id),
            title=title,
            original_title=original,
            year=_year_from_tvdb_record(record),
            overview=_tvdb_text(record, "overview", "overview_translated"),
        )

    @staticmethod
    def _tvdb_season_number(item: dict[str, Any]) -> int | None:
        value = next(
            (
                item.get(key)
                for key in ("seasonNumber", "season_number", "airedSeason", "officialSeasonNumber")
                if item.get(key) is not None
            ),
            None,
        )
        return _int_or_none(value)

    @staticmethod
    def _tvdb_episode_number(item: dict[str, Any]) -> int | None:
        value = next(
            (
                item.get(key)
                for key in ("number", "episodeNumber", "episode_number", "airedEpisodeNumber")
                if item.get(key) is not None
            ),
            None,
        )
        return _int_or_none(value)

    def _client(self, provider: str):
        try:
            return self._clients[str(provider)]
        except KeyError as exc:
            raise OnlineMetadataAuthError(f"Provider {provider!r} ist nicht eingerichtet.") from exc

    @staticmethod
    def _require_kind(hit: MetadataBrowserHit, expected: MetadataKind) -> None:
        if hit.kind != expected:
            raise ValueError(f"Erwarteter Metadatentyp: {expected}; erhalten: {hit.kind}")

    @staticmethod
    def _provider_label(provider: str) -> str:
        return "TheTVDB" if provider == "thetvdb" else "TMDB"


def build_explicit_rename_proposal(mapping: ExplicitFileMapping) -> MovieRenameProposal | SeriesRenameProposal:
    """Convert one browser mapping into a normal Renamer proposal.

    This is the only bridge into the existing rename commit path.  The proposal
    carries a single 100%-confidence candidate, so the normal collision checks,
    editable target-name column and filesystem commit stay intact.
    """
    if isinstance(mapping, ExplicitMovieFileMapping):
        return _build_explicit_movie_proposal(mapping)
    return _build_explicit_series_proposal(mapping)


def _build_explicit_movie_proposal(mapping: ExplicitMovieFileMapping) -> MovieRenameProposal:
    source = Path(mapping.source_path)
    hit = mapping.hit
    if hit.kind != "movie":
        raise ValueError("Filmzuordnung benötigt einen Film-Treffer.")
    parsed = parse_movie_release_name(source)
    parsed = replace(parsed, query_title=hit.title, year=hit.year, is_probable_series=False)
    candidate = MovieRenameCandidate(
        title=hit.title,
        year=hit.year,
        tmdb_id=hit.provider_id if hit.provider == "tmdb" else None,
        original_title=hit.original_title,
        provider=hit.provider,
        provider_id=hit.provider_id,
        score=1.0,
    )
    target_name = build_target_filename(hit.title, hit.year, source.suffix)
    target_path = source.with_name(target_name)
    target_exists = target_path.exists() and path_compare_key(target_path) != path_compare_key(source)
    warnings = (f"Explizite Filmzuordnung über {hit.provider_label} ({hit.provider_id}).",)
    if target_exists:
        warnings += ("Zieldatei existiert bereits.",)
    return MovieRenameProposal(
        source_path=source,
        parsed=parsed,
        candidates=(candidate,),
        selected=candidate,
        target_name=target_name,
        target_path=target_path,
        status="conflict" if target_exists else "ok",
        confidence=1.0,
        warnings=warnings,
        target_exists=target_exists,
        minimum_score_used=1.0,
        search_mode="explicit_mapping",
    )


def _build_explicit_series_proposal(mapping: ExplicitSeriesFileMapping) -> SeriesRenameProposal:
    source = Path(mapping.source_path)
    hit = mapping.hit
    if hit.kind != "series":
        raise ValueError("Serienzuordnung benötigt einen Serien-Treffer.")
    episodes = tuple(mapping.episodes)
    first = episodes[0]
    parsed_existing = parse_series_release_name(source)
    warnings = tuple(parsed_existing.warnings) if parsed_existing is not None else ()
    parsed = ParsedSeriesReleaseName(
        source_name=source.name,
        suffix=source.suffix,
        series=hit.title,
        season=int(mapping.season),
        episode=int(first.episode),
        episode_title=first.title,
        year=hit.year,
        release_group=getattr(parsed_existing, "release_group", "") if parsed_existing else "",
        technical_tags=getattr(parsed_existing, "technical_tags", ()) if parsed_existing else (),
        warnings=warnings,
        season_missing=False,
        episodes=tuple(item.episode for item in episodes),
        episode_titles=tuple(item.title for item in episodes),
    )
    candidate = SeriesRenameCandidate(
        series=hit.title,
        season=int(mapping.season),
        episode=int(first.episode),
        episode_title=first.title,
        year=hit.year,
        provider=hit.provider,
        provider_id=hit.provider_id,
        episode_id=first.provider_episode_id,
        score=1.0,
        match_reason="explizit zugeordnet",
        episodes=tuple(item.episode for item in episodes),
        episode_titles=tuple(item.title for item in episodes),
        title_mode=mapping.title_mode,
    )
    target_name = build_series_multi_target_filename(
        hit.title,
        mapping.season,
        [item.episode for item in episodes],
        [item.title for item in episodes],
        source.suffix,
        title_mode=mapping.title_mode,
    )
    target_path = source.with_name(target_name)
    target_exists = target_path.exists() and path_compare_key(target_path) != path_compare_key(source)
    warning_list = [
        f"Explizite Episodenzuordnung über {hit.provider_label} ({hit.provider_id}): "
        + "".join(f"E{item.episode:02d}" for item in episodes)
    ]
    if target_exists:
        warning_list.append("Zieldatei existiert bereits.")
    return SeriesRenameProposal(
        source_path=source,
        parsed=parsed,
        candidates=(candidate,),
        selected=candidate,
        target_name=target_name,
        target_path=target_path,
        status="conflict" if target_exists else "ok",
        confidence=1.0,
        warnings=tuple(warning_list),
        target_exists=target_exists,
        minimum_score_used=1.0,
        search_mode="explicit_mapping",
    )


def natural_path_key(path: str | Path) -> tuple[Any, ...]:
    """Natural, case-insensitive ordering for dropped episode files."""
    import re

    text = Path(path).name.casefold()
    parts = re.split(r"(\d+)", text)
    return tuple(int(part) if part.isdigit() else part for part in parts)


def dedupe_paths(paths: Iterable[str | Path]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        text = str(raw)
        key = path_compare_key(text)
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


__all__ = [
    "MetadataBrowserHit",
    "MetadataBrowserEpisode",
    "ExplicitMovieFileMapping",
    "ExplicitSeriesFileMapping",
    "ExplicitFileMapping",
    "RenamerMetadataBrowserService",
    "build_explicit_rename_proposal",
    "natural_path_key",
    "dedupe_paths",
]
