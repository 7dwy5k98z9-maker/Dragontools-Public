# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from .workflow_engine import WorkflowVerifyResult


_COMMON_FRAME_RATES = (
    Fraction(24000, 1001),
    Fraction(24, 1),
    Fraction(25, 1),
    Fraction(30000, 1001),
    Fraction(30, 1),
    Fraction(50, 1),
    Fraction(60000, 1001),
    Fraction(60, 1),
)


@dataclass
class MediaTimingInfo:
    path: str
    container_duration_s: float | None = None
    video_duration_s: float | None = None
    audio_duration_s: float | None = None
    subtitle_duration_s: float | None = None
    chapter_end_s: float | None = None
    video_frame_count: int | None = None
    frame_rate: Fraction | None = None
    avg_frame_rate: Fraction | None = None
    real_frame_rate: Fraction | None = None
    frame_rate_derived_from_source: bool = False
    frame_rate_mode: str = "unknown"  # CFR, VFR or unknown
    codec: str = ""
    video_stream_count: int = 0
    audio_stream_count: int = 0
    subtitle_stream_count: int = 0
    attachment_stream_count: int = 0
    has_b_frames: bool | None = None
    video_start_s: float | None = None
    audio_start_s: float | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def expected_video_duration_s(self) -> float | None:
        return calculate_expected_duration(self)


@dataclass
class TimestampProblem:
    should_repair: bool
    reason: str
    expected_duration_s: float | None = None
    reported_duration_s: float | None = None


@dataclass
class TimestampRepairResult:
    attempted: bool = False
    repaired: bool = False
    verify_result: WorkflowVerifyResult | None = None
    duration_s: float | None = None
    reason: str = ""
    command: list[str] | None = None
    timing_summary: list[str] | None = None
    retry_recommended: bool = False
    tool_returncode: int | None = None
    method: str = ""


@dataclass
class DurationRepairOutcome:
    attempted: bool = False
    repaired: bool = False
    verify_result: WorkflowVerifyResult | None = None
    archived_path: str | None = None
    remux_duration_s: float | None = None
    timestamp_fix_attempted: bool = False
    timestamp_fixed: bool = False
    timestamp_duration_s: float | None = None
    timestamp_repair_reason: str = ""
    timestamp_repair_cmd: list[str] | None = None
    # Legacy alias for older reports/tests. May also contain an MP4Box command.
    timestamp_ffmpeg_cmd: list[str] | None = None
    timing_summary: list[str] | None = None
    keep_failed_output: bool = False
    message: str = ""


def calculate_expected_duration(info: MediaTimingInfo) -> float | None:
    if not info.video_frame_count or info.video_frame_count <= 0:
        return None
    if info.frame_rate is None or info.frame_rate <= 0:
        return None
    return float(Fraction(info.video_frame_count, 1) / info.frame_rate)


def duration_close(
    value: float | None,
    expected: float | None,
    *,
    min_tolerance_s: float = 3.0,
    relative_tolerance: float = 0.02,
) -> bool:
    if value is None or expected is None or value <= 0 or expected <= 0:
        return False
    tolerance = max(min_tolerance_s, abs(expected) * relative_tolerance)
    return abs(float(value) - float(expected)) <= tolerance


def is_extreme_mismatch(value: float | None, expected: float | None) -> bool:
    if value is None or expected is None or value <= 0 or expected <= 0:
        return False
    value = float(value)
    expected = float(expected)
    if duration_close(value, expected, min_tolerance_s=5.0, relative_tolerance=0.05):
        return False
    diff = abs(value - expected)
    if value > expected:
        return value >= expected * 2.0 and diff >= 120.0
    return value <= expected * 0.5 and diff >= 120.0


def detect_timestamp_problem(
    info: MediaTimingInfo,
    *,
    expected_duration_s: float | None = None,
) -> TimestampProblem:
    """Decide whether a damaged CFR video timeline can be rebuilt safely."""
    frame_expected = calculate_expected_duration(info)
    if frame_expected is None:
        return TimestampProblem(False, "Keine zuverlässige Frame/FPS-Dauer vorhanden.")

    mode = (info.frame_rate_mode or "unknown").upper()
    source_derived_cfr = bool(getattr(info, "frame_rate_derived_from_source", False))
    if mode == "VFR" and not source_derived_cfr:
        return TimestampProblem(False, "Variable Framerate erkannt - keine blinde CFR-Reparatur.")
    if mode != "CFR" and not source_derived_cfr:
        return TimestampProblem(False, "Framerate-Modus nicht sicher als CFR erkannt.")

    supporting: list[float] = []
    for value in (
        expected_duration_s,
        info.audio_duration_s,
        info.chapter_end_s,
        info.subtitle_duration_s,
    ):
        if duration_close(value, frame_expected):
            supporting.append(float(value))

    if expected_duration_s is not None or info.audio_duration_s is not None or info.chapter_end_s is not None:
        if not supporting:
            return TimestampProblem(
                False,
                "Frame/FPS-Dauer passt nicht zu Quelle, Audio oder Kapiteln.",
                expected_duration_s=frame_expected,
            )

    reported_values = [info.video_duration_s, info.container_duration_s]
    bad_values = [value for value in reported_values if is_extreme_mismatch(value, frame_expected)]
    if not bad_values:
        return TimestampProblem(
            False,
            "Keine extreme Abweichung von Video- oder Containerdauer erkannt.",
            expected_duration_s=frame_expected,
        )

    reported = max(float(value) for value in bad_values if value is not None)
    reason = "Extreme Abweichung im Videostream erkannt."
    if source_derived_cfr:
        reason += " Framerate wurde aus Quelldauer und Frameanzahl abgeleitet."
    return TimestampProblem(
        True,
        reason,
        expected_duration_s=frame_expected,
        reported_duration_s=reported,
    )
