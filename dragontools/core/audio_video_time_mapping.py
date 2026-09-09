# -*- coding: utf-8 -*-
from __future__ import annotations

import math
from statistics import mean, median

from .audio_video_match_models import (
    AudioVideoMatcherSettings,
    CutRegion,
    MatchPoint,
    TimeMappingResult,
    VideoInfo,
)
from .audio_video_match_utils import _clamp

def select_landmark_times(duration_s: float) -> list[float]:
    duration = max(0.0, float(duration_s or 0.0))
    if duration <= 4.0:
        return [max(0.1, duration / 2.0)]
    percentages = (0.03, 0.05, 0.20, 0.40, 0.60, 0.80, 0.95, 0.98)
    values = [duration * pct for pct in percentages]
    if duration >= 120.0:
        values.extend([15.0, 30.0])
    clean: list[float] = []
    for value in sorted(values):
        clamped = _clamp(value, 1.0, max(1.0, duration - 1.0))
        if all(abs(clamped - existing) >= 2.0 for existing in clean):
            clean.append(clamped)
    return clean


def _linear_regression(points: list[MatchPoint]) -> tuple[float, float, float, float]:
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
    max_abs = max((abs(r) for r in residuals), default=0.0)
    return a, b, rmse, max_abs


def _confidence(points: list[MatchPoint], *, expected_count: int, model_error_s: float) -> float:
    if not points:
        return 0.0
    match_quality = mean(p.similarity for p in points) * 100.0
    missing_penalty = max(0.0, (expected_count - len(points)) / max(expected_count, 1) * 28.0)
    model_penalty = min(28.0, max(0.0, model_error_s) * 18.0)
    return _clamp(match_quality - missing_penalty - model_penalty, 0.0, 100.0)


def classify_time_mapping(
    points: list[MatchPoint],
    *,
    source_info: VideoInfo,
    target_info: VideoInfo,
    unmatched_reference_times: list[float] | None = None,
    expected_count: int | None = None,
    settings: AudioVideoMatcherSettings | None = None,
) -> TimeMappingResult:
    cfg = settings or AudioVideoMatcherSettings()
    valid = sorted(points, key=lambda p: p.reference_time_s)
    unmatched = sorted(float(t) for t in (unmatched_reference_times or []))
    warnings: list[str] = []

    if len(valid) < cfg.min_match_points:
        warnings.append("Zu wenige sichere Landmarken gefunden. Die Videos sind eventuell nicht dieselbe Folge/Version.")
        return TimeMappingResult(
            mode="D",
            offset_s=0.0,
            speed_factor=1.0,
            residual_error_s=999.0,
            drift_s=0.0,
            confidence_percent=0.0,
            match_points=valid,
            unmatched_reference_times=unmatched,
            source_info=source_info,
            target_info=target_info,
            warnings=warnings,
            can_process=False,
        )

    offsets = [p.matched_time_s - p.reference_time_s for p in valid]
    constant_offset = median(offsets)
    constant_error = max((abs(o - constant_offset) for o in offsets), default=0.0)
    drift = max(offsets) - min(offsets) if offsets else 0.0
    a, b, linear_rmse, linear_max = _linear_regression(valid)

    first_valid = valid[0].reference_time_s
    last_valid = valid[-1].reference_time_s
    interior_unmatched = [t for t in unmatched if first_valid < t < last_valid]
    jump_ranges: list[CutRegion] = []
    for left, right in zip(valid, valid[1:]):
        delta = (right.matched_time_s - right.reference_time_s) - (
            left.matched_time_s - left.reference_time_s
        )
        if abs(delta) >= cfg.cut_offset_jump_s:
            jump_ranges.append(CutRegion(left.reference_time_s, right.reference_time_s))

    if constant_error <= cfg.constant_offset_tolerance_s and not interior_unmatched and not jump_ranges:
        mode = "A"
        speed = 1.0
        offset = constant_offset
        model_error = constant_error
    elif (
        linear_rmse <= cfg.linear_residual_tolerance_s
        and linear_max <= cfg.linear_residual_tolerance_s * 2.0
        and abs(a - 1.0) <= cfg.max_speed_deviation
        and not interior_unmatched
    ):
        mode = "B"
        speed = a
        offset = b
        model_error = linear_rmse
    else:
        mode = "C"
        speed = a if abs(a - 1.0) <= cfg.max_speed_deviation else 1.0
        offset = b if abs(a - 1.0) <= cfg.max_speed_deviation else constant_offset
        model_error = max(linear_rmse, constant_error)
        if interior_unmatched:
            for t in interior_unmatched:
                jump_ranges.append(CutRegion(max(first_valid, t - 3.0), min(last_valid, t + 3.0)))
        if not jump_ranges:
            jump_ranges.append(CutRegion(first_valid, last_valid))
        warnings.append(
            "Innerhalb des gemeinsamen Inhalts wurde ein wechselnder Offset erkannt. "
            "Bitte ungefähre Schnittbereiche eintragen und fein analysieren."
        )

    confidence = _confidence(valid, expected_count=expected_count or len(valid), model_error_s=model_error)
    source_at_target_start = offset
    source_at_target_end = speed * float(target_info.duration_s or 0.0) + offset
    source_extra_start = max(0.0, source_at_target_start)
    source_extra_end = max(0.0, float(source_info.duration_s or 0.0) - source_at_target_end)
    target_extra_start = max(0.0, -source_at_target_start / max(speed, 0.001))
    target_extra_end = max(0.0, (source_at_target_end - float(source_info.duration_s or 0.0)) / max(speed, 0.001))
    common_start = target_extra_start if target_extra_start > cfg.edge_extra_warn_s else 0.0
    common_end = max(common_start, float(target_info.duration_s or 0.0) - target_extra_end)

    if source_extra_start > cfg.edge_extra_warn_s:
        warnings.append(
            f"Deutsche Quelle besitzt ca. {source_extra_start:.1f}s zusätzlich vor dem gemeinsamen Inhalt. "
            "Das ist Fall A/B und wird beim Audio getrimmt."
        )
    if source_extra_end > cfg.edge_extra_warn_s:
        warnings.append(
            f"Deutsche Quelle besitzt ca. {source_extra_end:.1f}s zusätzlich nach dem gemeinsamen Inhalt. "
            "Das Zielvideo definiert die finale Länge; die Audiospur wird am Ende zugeschnitten."
        )
    if target_extra_start > cfg.edge_extra_warn_s:
        warnings.append(
            f"Das Zielvideo enthält am Anfang ca. {target_extra_start:.1f}s zusätzlichen Inhalt ohne deutsche Audioentsprechung."
        )
    if target_extra_end > cfg.edge_extra_warn_s:
        warnings.append(
            f"Das Zielvideo enthält am Ende ca. {target_extra_end:.1f}s zusätzlichen Inhalt, "
            "für den keine deutsche Audioentsprechung gefunden wurde."
        )
    if confidence < cfg.confidence_block_percent:
        warnings.append("Match-Sicherheit zu niedrig für eine automatische Audioerstellung.")

    can_process = (
        mode in {"A", "B"}
        and confidence >= cfg.confidence_block_percent
        and target_extra_start <= cfg.target_extra_block_s
        and target_extra_end <= cfg.target_extra_block_s
    )
    return TimeMappingResult(
        mode=mode,
        offset_s=offset,
        speed_factor=speed,
        residual_error_s=model_error,
        drift_s=drift,
        confidence_percent=confidence,
        match_points=valid,
        unmatched_reference_times=unmatched,
        source_info=source_info,
        target_info=target_info,
        common_start_target_s=common_start,
        common_end_target_s=common_end,
        source_extra_start_s=source_extra_start,
        source_extra_end_s=source_extra_end,
        target_extra_start_s=target_extra_start,
        target_extra_end_s=target_extra_end,
        suspect_cut_ranges=_merge_regions(jump_ranges),
        warnings=warnings,
        can_process=can_process,
    )


def _merge_regions(regions: list[CutRegion]) -> list[CutRegion]:
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
