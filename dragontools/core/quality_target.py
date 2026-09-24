# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(slots=True, frozen=True)
class QualityTargetConfig:
    enabled: bool = False
    target_vmaf: float = 95.0
    sample_count: int = 3
    sample_duration_s: float = 10.0
    min_quality: int = 18
    max_quality: int = 30

    @classmethod
    def from_encoder_options(cls, options: dict | None) -> "QualityTargetConfig":
        data = dict(options or {})
        minimum = max(0, min(63, int(data.get("quality_target_min", 18))))
        maximum = max(0, min(63, int(data.get("quality_target_max", 30))))
        if minimum > maximum:
            minimum, maximum = maximum, minimum
        return cls(
            enabled=bool(data.get("quality_target_enabled", False)),
            target_vmaf=max(1.0, min(100.0, float(data.get("quality_target_vmaf", 95.0)))),
            sample_count=max(1, min(10, int(data.get("quality_target_samples", 3)))),
            sample_duration_s=max(2.0, min(60.0, float(data.get("quality_target_sample_duration_s", 10.0)))),
            min_quality=minimum,
            max_quality=maximum,
        )


@dataclass(slots=True, frozen=True)
class QualityTargetEvaluation:
    quality: int
    average_vmaf: float
    segment_scores: tuple[float, ...] = ()


@dataclass(slots=True)
class QualityTargetResult:
    attempted: bool = False
    applied: bool = False
    selected_quality: int | None = None
    selected_vmaf: float | None = None
    target_met: bool = False
    reason: str = ""
    evaluations: list[QualityTargetEvaluation] = field(default_factory=list)


def adaptive_quality_search(
    *,
    min_quality: int,
    max_quality: int,
    target_vmaf: float,
    evaluate: Callable[[int], float | None],
) -> tuple[int | None, list[QualityTargetEvaluation], bool]:
    """Findet den höchsten Qualitätswert (stärkste Kompression), der das VMAF-Ziel hält.

    Niedrigere CQ/CRF/QP-Werte bedeuten höhere Qualität. Die Suche setzt daher voraus,
    dass VMAF mit steigendem Qualitätswert im Regelfall sinkt. Nur tatsächlich gemessene
    Werte werden als Ergebnis verwendet; bei fehlender Messung wird abgebrochen.
    """
    lo = max(0, min(63, int(min_quality)))
    hi = max(0, min(63, int(max_quality)))
    if lo > hi:
        lo, hi = hi, lo
    target = max(1.0, min(100.0, float(target_vmaf)))
    measured: dict[int, QualityTargetEvaluation] = {}

    def measure(value: int) -> float | None:
        if value in measured:
            return measured[value].average_vmaf
        score = evaluate(value)
        if score is None:
            return None
        evaluation = QualityTargetEvaluation(value, float(score), ())
        measured[value] = evaluation
        return evaluation.average_vmaf

    hi_score = measure(hi)
    if hi_score is None:
        return None, list(measured.values()), False
    if hi_score >= target:
        return hi, list(measured.values()), True

    lo_score = measure(lo)
    if lo_score is None:
        return None, list(measured.values()), False
    if lo_score < target:
        return None, sorted(measured.values(), key=lambda item: item.quality), False

    best = lo
    failing = hi
    while failing - best > 1:
        mid = (best + failing) // 2
        score = measure(mid)
        if score is None:
            return None, sorted(measured.values(), key=lambda item: item.quality), False
        if score >= target:
            best = mid
        else:
            failing = mid

    return best, sorted(measured.values(), key=lambda item: item.quality), True
