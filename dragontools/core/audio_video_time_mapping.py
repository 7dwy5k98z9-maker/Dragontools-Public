# -*- coding: utf-8 -*-
from __future__ import annotations

from .audio_video_match_models import AudioVideoMatcherSettings, MatchPoint, TimeMappingResult, VideoInfo
from .audio_video_match_utils import _clamp
from .audio_video_time_mapping_edges import evaluate_edges
from .audio_video_time_mapping_fit import confidence as _confidence
from .audio_video_time_mapping_fit import fit_mapping, linear_regression as _linear_regression, merge_regions as _merge_regions


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
    if len(valid) < cfg.min_match_points:
        return _insufficient_result(valid, unmatched, source_info, target_info)

    fit = fit_mapping(valid, unmatched_reference_times=unmatched, settings=cfg)
    edge = evaluate_edges(
        source_info=source_info,
        target_info=target_info,
        offset_s=fit.offset_s,
        speed_factor=fit.speed_factor,
        settings=cfg,
    )
    score = _confidence(valid, expected_count=expected_count or len(valid), model_error_s=fit.residual_error_s)
    warnings = [*fit.warnings, *edge.warnings]
    if score < cfg.confidence_block_percent:
        warnings.append("Match-Sicherheit zu niedrig für eine automatische Audioerstellung.")
    can_process = (
        fit.mode in {"A", "B"}
        and score >= cfg.confidence_block_percent
        and edge.target_extra_start_s <= cfg.target_extra_block_s
        and edge.target_extra_end_s <= cfg.target_extra_block_s
    )
    return TimeMappingResult(
        mode=fit.mode,
        offset_s=fit.offset_s,
        speed_factor=fit.speed_factor,
        residual_error_s=fit.residual_error_s,
        drift_s=fit.drift_s,
        confidence_percent=score,
        match_points=valid,
        unmatched_reference_times=unmatched,
        source_info=source_info,
        target_info=target_info,
        common_start_target_s=edge.common_start_target_s,
        common_end_target_s=edge.common_end_target_s,
        source_extra_start_s=edge.source_extra_start_s,
        source_extra_end_s=edge.source_extra_end_s,
        target_extra_start_s=edge.target_extra_start_s,
        target_extra_end_s=edge.target_extra_end_s,
        suspect_cut_ranges=fit.suspect_cut_ranges,
        warnings=warnings,
        can_process=can_process,
    )


def _insufficient_result(valid, unmatched, source_info, target_info) -> TimeMappingResult:
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
        warnings=["Zu wenige sichere Landmarken gefunden. Die Videos sind eventuell nicht dieselbe Folge/Version."],
        can_process=False,
    )
