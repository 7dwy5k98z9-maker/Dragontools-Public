from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TrickplaySettings:
    enabled: bool = False
    only_missing: bool = True
    conflict_mode: str = "skip"
    width: int = 320
    tile_columns: int = 10
    tile_rows: int = 10
    interval_s: int = 10
    jpeg_quality: int = 90
    qscale: int = 4
    hwaccel: str = "cuda"
    max_jobs: int = 1
    source_mode: str = "output"

    @property
    def tile_label(self) -> str:
        return f"{max(1, self.tile_columns)}x{max(1, self.tile_rows)}"


@dataclass(frozen=True)
class TrickplayFfmpegStrategy:
    name: str
    hwaccel: str
    start_message: str
    success_message: str
    before_message: str | None = None
    force_hwdownload: bool = False
