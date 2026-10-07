# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass

from .trickplay_service import TrickplaySettings


@dataclass(frozen=True)
class NfoSettings:
    enabled: bool = False
    timing: str = "after"
    only_unambiguous: bool = True
    include_fileinfo: bool = True
    movie_target_name: str = "movie.nfo"
    conflict_mode: str = "skip"


@dataclass(frozen=True)
class PostProcessConfig:
    nfo: NfoSettings
    trickplay: TrickplaySettings

    @property
    def enabled(self) -> bool:
        return self.nfo.enabled or self.trickplay.enabled

    @property
    def after_conversion_enabled(self) -> bool:
        return (
            (self.nfo.enabled and self.nfo.timing == "after")
            or self.trickplay.enabled
        )


@dataclass
class PreparedNfo:
    """NFO staged while the video conversion is running.

    The staged file is deliberately not installed beside the final video until
    the video itself has passed verification/replace.  This keeps the fast
    "during conversion" mode from leaving an orphaned or misleading NFO behind
    when an encode fails.
    """

    staging_path: str
    target_path: str
    conflict_mode: str
    kind: str
    suggestion: object
    include_fileinfo: bool = True
    status: str = "prepared"
    message: str = ""
    staging_identity: tuple | None = None


@dataclass(frozen=True)
class PostProcessItem:
    kind: str
    status: str
    path: str = ""
    message: str = ""


@dataclass(frozen=True)
class PreparedTrickplay:
    staging_root: str
    target_root: str
    settings: TrickplaySettings
    identity: tuple[int, int]


@dataclass(frozen=True)
class PostProcessRunResult:
    created_paths: list[str]
    items: list[dict[str, str]]
    prepared_trickplay: PreparedTrickplay | None = None
