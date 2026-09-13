# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass

from .trickplay_service import TrickplaySettings


@dataclass(frozen=True)
class NfoSettings:
    enabled: bool = False
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


@dataclass(frozen=True)
class PostProcessItem:
    kind: str
    status: str
    path: str = ""
    message: str = ""


@dataclass(frozen=True)
class PostProcessRunResult:
    created_paths: list[str]
    items: list[dict[str, str]]
