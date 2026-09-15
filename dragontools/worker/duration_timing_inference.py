# -*- coding: utf-8 -*-
"""Frame-rate inference and presentation for repaired timelines."""
from __future__ import annotations

from fractions import Fraction

from .duration_repair_models import MediaTimingInfo, calculate_expected_duration, duration_close, is_extreme_mismatch
from .duration_timing_parsing import nearest_common_rate_loose


def derive_frame_rate_from_source_duration(info: MediaTimingInfo, expected_duration_s: float | None) -> None:
    if not expected_duration_s or expected_duration_s <= 0 or not info.video_frame_count or info.video_frame_count <= 0:
        return
    raw_fps = float(info.video_frame_count) / float(expected_duration_s)
    derived = nearest_common_rate_loose(raw_fps)
    if derived is None:
        return
    derived_duration = float(Fraction(info.video_frame_count, 1) / derived)
    if not duration_close(derived_duration, expected_duration_s, min_tolerance_s=3.0, relative_tolerance=0.003):
        return
    if info.audio_duration_s is not None and not duration_close(info.audio_duration_s, expected_duration_s, min_tolerance_s=5.0, relative_tolerance=0.02):
        return
    if not any(is_extreme_mismatch(value, derived_duration) for value in (info.video_duration_s, info.container_duration_s)):
        return
    reported_expected = calculate_expected_duration(info)
    implausible = (
        info.frame_rate is None
        or float(info.frame_rate) < 1.0
        or (reported_expected is not None and not duration_close(reported_expected, expected_duration_s))
        or (info.frame_rate_mode or "").upper() == "VFR"
    )
    if not implausible:
        return
    info.frame_rate = derived
    info.frame_rate_derived_from_source = True
    info.frame_rate_mode = "CFR"
    info.warnings.append("Framerate wurde wegen defekter Timeline aus Quelldauer und Frameanzahl abgeleitet.")


def infer_frame_rate_mode(info: MediaTimingInfo) -> str:
    if info.frame_rate is None:
        return "unknown"
    if info.avg_frame_rate is not None and info.real_frame_rate is not None:
        return "CFR" if info.avg_frame_rate == info.real_frame_rate else "unknown"
    if info.expected_video_duration_s is not None and duration_close(info.video_duration_s, info.expected_video_duration_s, min_tolerance_s=2.0, relative_tolerance=0.01):
        return "CFR"
    return "unknown"


def derived_fps_suffix(info: MediaTimingInfo) -> str:
    return " (aus Quelle/Frames abgeleitet)" if info.frame_rate_derived_from_source else ""


def fps_label(fps: Fraction | None) -> str:
    if fps is None:
        return "unbekannt"
    return f"{fps.numerator}/{fps.denominator}"


__all__ = ["derive_frame_rate_from_source_duration", "infer_frame_rate_mode", "derived_fps_suffix", "fps_label"]
