# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field

from ..core.settings import (
    DEFAULT_SOURCE_VISUAL_CHECK_BLOCK_PERCENT,
    DEFAULT_SOURCE_VISUAL_CHECK_ENABLED,
    DEFAULT_SOURCE_VISUAL_CHECK_FPS,
    DEFAULT_SOURCE_VISUAL_CHECK_INTERVAL_PERCENT,
    DEFAULT_SOURCE_VISUAL_CHECK_MIN_HITS,
    DEFAULT_SOURCE_VISUAL_CHECK_SAMPLE_DURATION_S,
)


@dataclass(frozen=True)
class SourceVisualCheckSettings:
    enabled: bool = DEFAULT_SOURCE_VISUAL_CHECK_ENABLED
    interval_percent: int = DEFAULT_SOURCE_VISUAL_CHECK_INTERVAL_PERCENT
    sample_duration_s: int = DEFAULT_SOURCE_VISUAL_CHECK_SAMPLE_DURATION_S
    fps: int = DEFAULT_SOURCE_VISUAL_CHECK_FPS
    block_percent: int = DEFAULT_SOURCE_VISUAL_CHECK_BLOCK_PERCENT
    min_hits: int = DEFAULT_SOURCE_VISUAL_CHECK_MIN_HITS
    analysis_width: int = 96
    analysis_height: int = 54


@dataclass(frozen=True)
class SourceVisualProbe:
    percent: int
    timestamp_s: float
    suspicious: bool
    reason: str = ""
    frames: int = 0


@dataclass(frozen=True)
class SourceVisualCheckResult:
    enabled: bool
    blocked: bool = False
    duration_s: float = 0.0
    probes: list[SourceVisualProbe] = field(default_factory=list)
    message: str = ""

    @property
    def suspicious_count(self) -> int:
        return sum(1 for probe in self.probes if probe.suspicious)

    @property
    def suspicious_percent(self) -> float:
        if not self.probes:
            return 0.0
        return self.suspicious_count / len(self.probes) * 100.0

    def summary_line(self) -> str:
        if not self.enabled:
            return "Quellbildprüfung deaktiviert."
        if not self.probes:
            return self.message or "Quellbildprüfung ohne Prüfpunkte abgeschlossen."
        state = "blockiert" if self.blocked else "unauffällig"
        return (
            f"Quellbildprüfung {state}: {self.suspicious_count}/{len(self.probes)} "
            f"Prüfpunkte auffällig ({self.suspicious_percent:.0f}%)."
        )

    def report_lines(self, *, include_ok: bool = False) -> list[str]:
        lines = [self.summary_line()]
        if self.message and self.message not in lines[0]:
            lines.append(self.message)
        for probe in self.probes:
            if not include_ok and not probe.suspicious:
                continue
            status = "auffällig" if probe.suspicious else "OK"
            reason = f" - {probe.reason}" if probe.reason else ""
            lines.append(
                f"  {probe.percent:>3}% / {format_seconds(probe.timestamp_s)}: "
                f"{status} ({probe.frames} Frame(s)){reason}"
            )
        return lines


def format_seconds(seconds: float) -> str:
    seconds = max(0, int(round(float(seconds or 0))))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


__all__ = [
    "SourceVisualCheckSettings",
    "SourceVisualProbe",
    "SourceVisualCheckResult",
    "format_seconds",
]
