from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AnalyzerConfig:
    """Future analysis tuning without coupling the CLI to one decoder backend."""

    backend: str = "cpu"
    scene_histogram_bins: int = 256
    percentile_points: tuple[float, ...] = (90.0, 95.0, 99.0, 99.9)
    min_scene_frames: int = 2
