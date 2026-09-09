from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ..core.settings import (
    DEFAULT_SOURCE_VISUAL_CHECK_BLOCK_PERCENT,
    DEFAULT_SOURCE_VISUAL_CHECK_ENABLED,
    DEFAULT_SOURCE_VISUAL_CHECK_FPS,
    DEFAULT_SOURCE_VISUAL_CHECK_INTERVAL_PERCENT,
    DEFAULT_SOURCE_VISUAL_CHECK_MIN_HITS,
    DEFAULT_SOURCE_VISUAL_CHECK_SAMPLE_DURATION_S,
    SET_KEY_SOURCE_VISUAL_CHECK_BLOCK_PERCENT,
    SET_KEY_SOURCE_VISUAL_CHECK_ENABLED,
    SET_KEY_SOURCE_VISUAL_CHECK_FPS,
    SET_KEY_SOURCE_VISUAL_CHECK_INTERVAL_PERCENT,
    SET_KEY_SOURCE_VISUAL_CHECK_MIN_HITS,
    SET_KEY_SOURCE_VISUAL_CHECK_SAMPLE_DURATION_S,
    settings_bool,
    settings_int,
)
from ..core.process_runner import subprocess_no_window_kwargs as _no_window_kwargs


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


def source_visual_settings_from_qsettings(settings) -> SourceVisualCheckSettings:
    return SourceVisualCheckSettings(
        enabled=settings_bool(
            settings,
            SET_KEY_SOURCE_VISUAL_CHECK_ENABLED,
            DEFAULT_SOURCE_VISUAL_CHECK_ENABLED,
        ),
        interval_percent=settings_int(
            settings,
            SET_KEY_SOURCE_VISUAL_CHECK_INTERVAL_PERCENT,
            DEFAULT_SOURCE_VISUAL_CHECK_INTERVAL_PERCENT,
            minimum=5,
            maximum=50,
        ),
        sample_duration_s=settings_int(
            settings,
            SET_KEY_SOURCE_VISUAL_CHECK_SAMPLE_DURATION_S,
            DEFAULT_SOURCE_VISUAL_CHECK_SAMPLE_DURATION_S,
            minimum=1,
            maximum=10,
        ),
        fps=settings_int(
            settings,
            SET_KEY_SOURCE_VISUAL_CHECK_FPS,
            DEFAULT_SOURCE_VISUAL_CHECK_FPS,
            minimum=1,
            maximum=10,
        ),
        block_percent=settings_int(
            settings,
            SET_KEY_SOURCE_VISUAL_CHECK_BLOCK_PERCENT,
            DEFAULT_SOURCE_VISUAL_CHECK_BLOCK_PERCENT,
            minimum=50,
            maximum=100,
        ),
        min_hits=settings_int(
            settings,
            SET_KEY_SOURCE_VISUAL_CHECK_MIN_HITS,
            DEFAULT_SOURCE_VISUAL_CHECK_MIN_HITS,
            minimum=1,
            maximum=20,
        ),
    )


class SourceVisualCheckService:
    def __init__(self, *, ffmpeg_path: str, ffprobe_path: str) -> None:
        self.ffmpeg_path = str(ffmpeg_path or "")
        self.ffprobe_path = str(ffprobe_path or "")

    def check(self, path: str | Path, settings: SourceVisualCheckSettings) -> SourceVisualCheckResult:
        if not settings.enabled:
            return SourceVisualCheckResult(enabled=False)

        video = Path(path)
        if not video.exists():
            return SourceVisualCheckResult(
                enabled=True,
                message="Datei nicht gefunden.",
            )
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

        probes: list[SourceVisualProbe] = []
        for percent in self._probe_percents(settings):
            start = min(
                max(0.0, duration * percent / 100.0),
                max(0.0, duration - float(settings.sample_duration_s)),
            )
            probe = self._probe_segment(video, percent, start, settings)
            probes.append(probe)

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

    def _probe_duration(self, path: Path) -> float:
        try:
            result = subprocess.run(
                [
                    self.ffprobe_path,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "json",
                    str(path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdin=subprocess.DEVNULL,
                **_no_window_kwargs(),
                timeout=20,
            )
            data = json.loads(result.stdout or "{}")
            return float((data.get("format") or {}).get("duration") or 0.0)
        except Exception:
            return 0.0

    def _probe_percents(self, settings: SourceVisualCheckSettings) -> list[int]:
        step = max(5, min(50, int(settings.interval_percent or 10)))
        values = list(range(step, 100, step))
        values = [value for value in values if 5 <= value <= 95]
        if not values:
            values = [50]
        return values[:20]

    def _probe_segment(
        self,
        path: Path,
        percent: int,
        start_s: float,
        settings: SourceVisualCheckSettings,
    ) -> SourceVisualProbe:
        raw = self._read_probe_frames(path, start_s, settings)
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
        findings = [self._analyze_frame(frame, settings.analysis_width, settings.analysis_height) for frame in frames]
        suspicious_findings = [reason for ok, reason in findings if ok]
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

    def _read_probe_frames(
        self,
        path: Path,
        start_s: float,
        settings: SourceVisualCheckSettings,
    ) -> bytes:
        width = int(settings.analysis_width)
        height = int(settings.analysis_height)
        vf = (
            f"fps={max(1, int(settings.fps))},"
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
            "format=rgb24"
        )
        cmd = [
            self.ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{max(0.0, start_s):.3f}",
            "-t",
            str(max(1, int(settings.sample_duration_s))),
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-an",
            "-sn",
            "-vf",
            vf,
            "-f",
            "rawvideo",
            "-",
        ]
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                **_no_window_kwargs(),
                timeout=max(15, int(settings.sample_duration_s) + 15),
            )
            if result.returncode != 0:
                return b""
            return bytes(result.stdout or b"")
        except Exception:
            return b""

    def _analyze_frame(self, frame: bytes, width: int, height: int) -> tuple[bool, str]:
        pixel_count = max(1, len(frame) // 3)
        channels = len(frame)
        mean = sum(frame) / max(1, channels)
        variance = sum((value - mean) ** 2 for value in frame) / max(1, channels)

        r_mean = sum(frame[0::3]) / pixel_count
        g_mean = sum(frame[1::3]) / pixel_count
        b_mean = sum(frame[2::3]) / pixel_count
        channel_delta = max(r_mean, g_mean, b_mean) - min(r_mean, g_mean, b_mean)

        neighbor_diff = self._mean_neighbor_diff(frame, width, height)
        if variance < 8.0 and (mean < 12.0 or mean > 243.0):
            return True, "nahezu leer/schwarz/weiß"
        if neighbor_diff < 1.5 and channel_delta > 28.0:
            return True, "einfarbige auffällige Fläche"

        if neighbor_diff > 58.0 and channel_delta > 22.0 and variance > 2200.0:
            return True, "starkes Pixelrauschen"

        return False, ""

    def _mean_neighbor_diff(self, frame: bytes, width: int, height: int) -> float:
        if width <= 1 or height <= 1:
            return 0.0
        total = 0.0
        count = 0
        for y in range(height):
            row = y * width
            for x in range(width - 1):
                a = _luma(frame, row + x)
                b = _luma(frame, row + x + 1)
                total += abs(a - b)
                count += 1
        for y in range(height - 1):
            row = y * width
            next_row = (y + 1) * width
            for x in range(width):
                a = _luma(frame, row + x)
                b = _luma(frame, next_row + x)
                total += abs(a - b)
                count += 1
        return total / max(1, count)


def _luma(frame: bytes, pixel_index: int) -> float:
    offset = pixel_index * 3
    try:
        return frame[offset] * 0.2126 + frame[offset + 1] * 0.7152 + frame[offset + 2] * 0.0722
    except IndexError:
        return 0.0


def most_common_reason(reasons: list[str]) -> str:
    if not reasons:
        return ""
    counts: dict[str, int] = {}
    for reason in reasons:
        counts[reason] = counts.get(reason, 0) + 1
    return max(counts.items(), key=lambda item: item[1])[0]
