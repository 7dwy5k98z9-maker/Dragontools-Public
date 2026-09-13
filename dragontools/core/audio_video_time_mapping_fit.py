# -*- coding: utf-8 -*-
from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import mean, median

from .audio_video_match_models import AudioVideoMatcherSettings, CutRegion, MatchPoint
from .audio_video_match_utils import _clamp


@dataclass(slots=True)
class MappingFit:
    mode: str
    offset_s: float
    speed_factor: float
    residual_error_s: float
    drift_s: float
    suspect_cut_ranges: list[CutRegion] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def linear_regression(points: list[MatchPoint]) -> tuple[float, float, float, float]:
    xs = [p.reference_time_s for p in points]
    ys = [p.matched_time_s for p in points]
    x_mean = mean(xs)
    y_mean = mean(ys)
    denom = sum((x - x_mean) ** 2 for x in xs)
    if denom <= 0.0:
        return 1.0, y_mean - x_mean, 0.0, 0.0
    a = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / denom
    b = y_mean - a * x_mean
    residuals = [y - (a * x + b) for x, y in zip(xs, ys)]
    rmse = math.sqrt(sum(r * r for r in residuals) / max(len(residuals), 1))
    return a, b, rmse, max((abs(r) for r in residuals), default=0.0)


def confidence(points: list[MatchPoint], *, expected_count: int, model_error_s: float) -> float:
    if not points:
        return 0.0
    quality = mean(p.similarity for p in points) * 100.0
    missing_penalty = max(0.0, (expected_count - len(points)) / max(expected_count, 1) * 28.0)
    model_penalty = min(28.0, max(0.0, model_error_s) * 18.0)
    return _clamp(quality - missing_penalty - model_penalty, 0.0, 100.0)


def fit_mapping(
    points: list[MatchPoint],
    *,
    unmatched_reference_times: list[float],
    settings: AudioVideoMatcherSettings,
) -> MappingFit:
    offsets = [p.matched_time_s - p.reference_time_s for p in points]
    constant_offset = median(offsets)
    constant_error = max((abs(o - constant_offset) for o in offsets), default=0.0)
    drift = max(offsets) - min(offsets) if offsets else 0.0
    a, b, linear_rmse, linear_max = linear_regression(points)

    first_valid = points[0].reference_time_s
    last_valid = points[-1].reference_time_s
    interior_unmatched = [t for t in unmatched_reference_times if first_valid < t < last_valid]
    jump_ranges = _offset_jump_ranges(points, settings.cut_offset_jump_s)

    if constant_error <= settings.constant_offset_tolerance_s and not interior_unmatched and not jump_ranges:
        return MappingFit("A", constant_offset, 1.0, constant_error, drift)
    if (
        linear_rmse <= settings.linear_residual_tolerance_s
        and linear_max <= settings.linear_residual_tolerance_s * 2.0
        and abs(a - 1.0) <= settings.max_speed_deviation
        and not interior_unmatched
    ):
        return MappingFit("B", b, a, linear_rmse, drift)

    speed = a if abs(a - 1.0) <= settings.max_speed_deviation else 1.0
    offset = b if abs(a - 1.0) <= settings.max_speed_deviation else constant_offset
    if interior_unmatched:
        jump_ranges.extend(
            CutRegion(max(first_valid, t - 3.0), min(last_valid, t + 3.0))
            for t in interior_unmatched
        )
    if not jump_ranges:
        jump_ranges.append(CutRegion(first_valid, last_valid))
    return MappingFit(
        "C",
        offset,
        speed,
        max(linear_rmse, constant_error),
        drift,
        suspect_cut_ranges=merge_regions(jump_ranges),
        warnings=[
            "Innerhalb des gemeinsamen Inhalts wurde ein wechselnder Offset erkannt. "
            "Bitte ungefähre Schnittbereiche eintragen und fein analysieren."
        ],
    )


def _offset_jump_ranges(points: list[MatchPoint], threshold_s: float) -> list[CutRegion]:
    ranges: list[CutRegion] = []
    for left, right in zip(points, points[1:]):
        delta = (right.matched_time_s - right.reference_time_s) - (left.matched_time_s - left.reference_time_s)
        if abs(delta) >= threshold_s:
            ranges.append(CutRegion(left.reference_time_s, right.reference_time_s))
    return ranges


def merge_regions(regions: list[CutRegion]) -> list[CutRegion]:
    if not regions:
        return []
    ordered = sorted(regions, key=lambda r: (r.start_s, r.end_s))
    merged: list[CutRegion] = []
    for region in ordered:
        if not merged or region.start_s > merged[-1].end_s:
            merged.append(CutRegion(region.start_s, region.end_s))
        else:
            merged[-1] = CutRegion(merged[-1].start_s, max(merged[-1].end_s, region.end_s))
    return merged
