# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from ..rules.renamer_rules import auto_accept_from


def _provider_label(provider: str) -> str:
    value = str(provider or "").strip().lower()
    if value == "thetvdb":
        return "TheTVDB"
    if value == "tmdb":
        return "TMDB"
    return "Metadaten"

@dataclass(frozen=True)
class ParsedMovieReleaseName:
    source_name: str
    suffix: str
    query_title: str
    year: int | None
    is_probable_series: bool = False
    release_group: str = ""
    edition_hints: tuple[str, ...] = ()
    technical_tags: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class MovieRenameCandidate:
    title: str
    year: int | None
    tmdb_id: int | None = None
    original_title: str = ""
    provider: str = "tmdb"
    provider_id: int | None = None
    score: float = 0.0

    @property
    def display_title(self) -> str:
        if self.year:
            return f"{self.title} ({self.year})"
        return self.title

    @property
    def choice_label(self) -> str:
        provider = _provider_label(self.provider)
        score = f" · {int(round(self.score * 100))} %" if self.score else ""
        return f"{self.display_title} · {provider}{score}"


@dataclass(frozen=True)
class MovieRenameProposal:
    source_path: Path
    parsed: ParsedMovieReleaseName
    candidates: tuple[MovieRenameCandidate, ...] = ()
    selected: MovieRenameCandidate | None = None
    target_name: str = ""
    target_path: Path | None = None
    status: str = "no_match"
    confidence: float = 0.0
    warnings: tuple[str, ...] = ()
    target_exists: bool = False
    minimum_score_used: float = 0.0
    search_mode: str = "auto"

    @property
    def can_auto_accept(self) -> bool:
        return self.status == "ok" and self.confidence >= auto_accept_from() and not self.target_exists


@dataclass(frozen=True)
class ParsedSeriesReleaseName:
    source_name: str
    suffix: str
    series: str
    season: int
    episode: int
    episode_title: str = ""
    year: int | None = None
    release_group: str = ""
    technical_tags: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def query_title(self) -> str:
        return self.series


@dataclass(frozen=True)
class SeriesRenameCandidate:
    series: str
    season: int
    episode: int
    episode_title: str = ""
    year: int | None = None
    provider: str = "metadata"
    provider_id: int | None = None
    episode_id: int | None = None
    score: float = 0.0
    match_reason: str = ""  # DragonTools patch: fuzzy display confidence v6

    @property
    def display_title(self) -> str:
        ep = f"S{self.season:02d}E{self.episode:02d}"
        title = f" - {self.episode_title}" if self.episode_title else ""
        year = f" ({self.year})" if self.year else ""
        return f"{self.series}{year} - {ep}{title}"

    @property
    def choice_label(self) -> str:
        provider = _provider_label(self.provider)
        score = f" · {int(round(self.score * 100))} %" if self.score else ""
        reason = f" · {self.match_reason}" if self.match_reason else ""
        return f"{self.display_title} · {provider}{score}{reason}"


@dataclass(frozen=True)
class SeriesRenameProposal:
    source_path: Path
    parsed: ParsedSeriesReleaseName
    candidates: tuple[SeriesRenameCandidate, ...] = ()
    selected: SeriesRenameCandidate | None = None
    target_name: str = ""
    target_path: Path | None = None
    status: str = "no_match"
    confidence: float = 0.0
    warnings: tuple[str, ...] = ()
    target_exists: bool = False
    minimum_score_used: float = 0.0
    search_mode: str = "auto"

    @property
    def can_auto_accept(self) -> bool:
        return self.status == "ok" and self.confidence >= auto_accept_from() and not self.target_exists


RenameProposal = MovieRenameProposal | SeriesRenameProposal
MovieSearchResolver = Callable[[str, int | None], Iterable[Any]]
SeriesSearchResolver = Callable[[str, int, int, int | None], Iterable[Any]]
