# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from .source_visual_analysis import (
    analyze_frame as _analyze_visual_frame,
    luma as _luma_impl,
    mean_neighbor_diff as _mean_neighbor_diff_impl,
    most_common_reason,
)
from .source_visual_models import (
    SourceVisualCheckResult,
    SourceVisualCheckSettings,
    SourceVisualProbe,
    format_seconds,
)
from .source_visual_sampling import SourceVisualSampler
from .source_visual_settings import source_visual_settings_from_qsettings


class SourceVisualCheckService:
    """Orchestrates source visual sampling and corruption heuristics."""

    def __init__(self, *, ffmpeg_path: str, ffprobe_path: str) -> None:
        self.ffmpeg_path = str(ffmpeg_path or "")
        self.ffprobe_path = str(ffprobe_path or "")
        self._sampler = SourceVisualSampler(
            ffmpeg_path=self.ffmpeg_path,
            ffprobe_path=self.ffprobe_path,
        )

    def check(self, path: str | Path, settings: SourceVisualCheckSettings) -> SourceVisualCheckResult:
        if not settings.enabled:
            return SourceVisualCheckResult(enabled=False)

        video = Path(path)
        if not video.exists():
            return SourceVisualCheckResult(enabled=True, message="Datei nicht gefunden.")
        if not self.ffmpeg_path or not self.ffprobe_path:
            return SourceVisualCheckResult(
                enabled=True,
                message="ffmpeg oder ffprobe nicht gefunden; Quellbildprüfung übersprungen.",
            )

        duration = self._probe_duration(video)
        if duration <= 0:
            return SourceVisualCheckResult(
                enabled=True,
                duration_s=0.0,
                message="Laufzeit nicht ermittelbar; Quellbildprüfung übersprungen.",
            )

        probe_specs = [
            (
                percent,
                min(
                    max(0.0, duration * percent / 100.0),
                    max(0.0, duration - float(settings.sample_duration_s)),
                ),
            )
            for percent in self._probe_percents(settings)
        ]
        probes = self._probe_segments(video, probe_specs, settings)
        suspicious = sum(1 for probe in probes if probe.suspicious)
        suspicious_percent = (suspicious / len(probes) * 100.0) if probes else 0.0
        blocked = (
            bool(probes)
            and suspicious >= max(1, settings.min_hits)
            and suspicious_percent >= float(settings.block_percent)
        )
        return SourceVisualCheckResult(
            enabled=True,
            blocked=blocked,
            duration_s=duration,
            probes=probes,
        )

    def _probe_segments(
        self,
        path: Path,
        probe_specs: list[tuple[int, float]],
        settings: SourceVisualCheckSettings,
    ) -> list[SourceVisualProbe]:
        if not probe_specs:
            return []

        # Preserve the existing monkeypatch/extension seam. Callers that
        # override the single-probe reader keep the exact old execution path.
        if "_read_probe_frames" in self.__dict__:
            return [
                self._probe_segment(path, percent, start_s, settings)
                for percent, start_s in probe_specs
            ]

        raw_frames = self._read_probe_frames_batch(
            path,
            [start_s for _percent, start_s in probe_specs],
            settings,
        )
        return [
            self._probe_segment_from_raw(percent, start_s, settings, raw)
            for (percent, start_s), raw in zip(probe_specs, raw_frames)
        ]

    def _probe_segment_from_raw(
        self,
        percent: int,
        start_s: float,
        settings: SourceVisualCheckSettings,
        raw: bytes,
    ) -> SourceVisualProbe:
        frame_size = settings.analysis_width * settings.analysis_height * 3
        if not raw or len(raw) < frame_size:
            return SourceVisualProbe(
                percent=percent,
                timestamp_s=start_s,
                suspicious=True,
                reason="keine dekodierbaren Frames",
                frames=0,
            )

        frames = [
            raw[index:index + frame_size]
            for index in range(0, len(raw) - frame_size + 1, frame_size)
        ]
        findings = [
            self._analyze_frame(frame, settings.analysis_width, settings.analysis_height)
            for frame in frames
        ]
        suspicious_findings = [reason for is_suspicious, reason in findings if is_suspicious]
        suspicious_ratio = len(suspicious_findings) / max(1, len(frames))
        suspicious = suspicious_ratio >= 0.75
        reason = most_common_reason(suspicious_findings) if suspicious else ""
        return SourceVisualProbe(
            percent=percent,
            timestamp_s=start_s,
            suspicious=suspicious,
            reason=reason,
            frames=len(frames),
        )

    def _probe_segment(
        self,
        path: Path,
        percent: int,
        start_s: float,
        settings: SourceVisualCheckSettings,
    ) -> SourceVisualProbe:
        raw = self._read_probe_frames(path, start_s, settings)
        return self._probe_segment_from_raw(percent, start_s, settings, raw)

    def _read_probe_frames_batch(
        self,
        path: Path,
        start_points: list[float],
        settings: SourceVisualCheckSettings,
        *,
        batch_size: int = 4,
    ) -> list[bytes]:
        """Reduce FFmpeg startups while retaining fail-safe single-probe fallback."""
        size = max(1, min(int(batch_size or 1), 8))
        results: list[bytes] = []
        for offset in range(0, len(start_points), size):
            group = start_points[offset:offset + size]
            batch = self._read_probe_frame_group(path, group, settings)
            if batch is None or len(batch) != len(group):
                results.extend(
                    self._read_probe_frames(path, start_s, settings)
                    for start_s in group
                )
            else:
                results.extend(batch)
        return results

    # Compatibility wrappers keep the previous private seams available to tests
    # and extensions while process execution/analysis live in dedicated modules.
    def _probe_duration(self, path: Path) -> float:
        return self._sampler.probe_duration(path)

    @staticmethod
    def _probe_percents(settings: SourceVisualCheckSettings) -> list[int]:
        step = max(5, min(50, int(settings.interval_percent or 10)))
        values = [value for value in range(step, 100, step) if 5 <= value <= 95]
        return (values or [50])[:20]

    def _read_probe_frames(
        self,
        path: Path,
        start_s: float,
        settings: SourceVisualCheckSettings,
    ) -> bytes:
        return self._sampler.read_single(path, start_s, settings)

    def _read_probe_frame_group(
        self,
        path: Path,
        start_points: list[float],
        settings: SourceVisualCheckSettings,
    ) -> list[bytes] | None:
        return self._sampler.read_group(path, start_points, settings)

    @staticmethod
    def _analyze_frame(frame: bytes, width: int, height: int) -> tuple[bool, str]:
        return _analyze_visual_frame(frame, width, height)

    @staticmethod
    def _mean_neighbor_diff(frame: bytes, width: int, height: int) -> float:
        return _mean_neighbor_diff_impl(frame, width, height)


def _luma(frame: bytes, pixel_index: int) -> float:
    """Private compatibility alias retained for existing imports/tests."""
    return _luma_impl(frame, pixel_index)


__all__ = [
    "SourceVisualCheckResult",
    "SourceVisualCheckService",
    "SourceVisualCheckSettings",
    "SourceVisualProbe",
    "format_seconds",
    "most_common_reason",
    "source_visual_settings_from_qsettings",
]
