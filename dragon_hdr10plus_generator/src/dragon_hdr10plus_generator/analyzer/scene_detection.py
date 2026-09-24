from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True, slots=True)
class HistogramFrame:
    frame_index: int
    bins: tuple[float, ...]


def histogram_distance(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("histograms must have the same non-zero bin count")
    left_total = sum(max(0.0, float(v)) for v in left) or 1.0
    right_total = sum(max(0.0, float(v)) for v in right) or 1.0
    return 0.5 * sum(
        abs(max(0.0, float(a)) / left_total - max(0.0, float(b)) / right_total)
        for a, b in zip(left, right)
    )


def candidate_boundaries(
    frames: Iterable[HistogramFrame],
    *,
    threshold: float,
    min_scene_frames: int = 2,
) -> tuple[int, ...]:
    """Return deterministic candidate boundaries; final tuning remains future work."""
    items = list(frames)
    if len(items) < 2:
        return ()
    out: list[int] = []
    last_boundary = items[0].frame_index
    for previous, current in zip(items, items[1:]):
        if current.frame_index - last_boundary < max(1, int(min_scene_frames)):
            continue
        if histogram_distance(previous.bins, current.bins) >= float(threshold):
            out.append(current.frame_index)
            last_boundary = current.frame_index
    return tuple(out)


__all__ = ["HistogramFrame", "candidate_boundaries", "histogram_distance"]
