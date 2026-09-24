from __future__ import annotations

from dataclasses import dataclass
from math import floor
from typing import Iterable


@dataclass(frozen=True, slots=True)
class DistributionSummary:
    minimum: float
    maximum: float
    mean: float
    percentiles: dict[float, float]


def percentile(values: Iterable[float], point: float) -> float:
    data = sorted(float(v) for v in values)
    if not data:
        raise ValueError("percentile() requires at least one sample")
    q = min(100.0, max(0.0, float(point))) / 100.0
    if len(data) == 1:
        return data[0]
    rank = q * (len(data) - 1)
    low = floor(rank)
    high = min(low + 1, len(data) - 1)
    fraction = rank - low
    return data[low] + (data[high] - data[low]) * fraction


def summarize_distribution(
    values: Iterable[float],
    *,
    percentile_points: Iterable[float] = (90.0, 95.0, 99.0, 99.9),
) -> DistributionSummary:
    data = [float(v) for v in values]
    if not data:
        raise ValueError("summarize_distribution() requires at least one sample")
    return DistributionSummary(
        minimum=min(data),
        maximum=max(data),
        mean=sum(data) / len(data),
        percentiles={float(p): percentile(data, float(p)) for p in percentile_points},
    )


__all__ = ["DistributionSummary", "percentile", "summarize_distribution"]
