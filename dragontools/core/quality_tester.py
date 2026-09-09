# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .codec_utils import normalize_target_codec


@dataclass(slots=True)
class QualitySegment:
    start_s: float
    duration_s: float
    label: str


@dataclass(slots=True)
class QualityTestRun:
    name: str
    codec: str = "h265"
    encoder: str = "cpu"
    quality: int = 23
    preset: str = "medium"
    pix_fmt: str = "10-bit"
    scale: str = "original"
    extra_args: str = ""
    encoder_options: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class QualityMetricResult:
    run_name: str
    segment_label: str
    output_path: str
    size_bytes: int = 0
    duration_s: float = 0.0
    video_bitrate_kbps: float = 0.0
    codec: str = ""
    pix_fmt: str = ""
    profile: str = ""
    ssim: float | None = None
    vmaf: float | None = None
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class QualityFileInfo:
    path: str
    name: str
    size_bytes: int = 0
    duration_s: float = 0.0
    width: int = 0
    height: int = 0
    codec: str = ""
    pix_fmt: str = ""
    frame_rate: str = ""
    hdr_label: str = "SDR"


@dataclass(slots=True)
class QualityComparisonResult:
    segment_label: str
    start_a_s: float
    start_b_s: float
    duration_s: float
    ssim: float | None = None
    vmaf: float | None = None
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class QualityComparisonSummary:
    file_a: QualityFileInfo
    file_b: QualityFileInfo
    average_ssim: float | None = None
    average_vmaf: float | None = None
    compared_segments: int = 0
    assessment: str = ""
    notes: list[str] = field(default_factory=list)


def comparison_duration_limit(duration_a_s: float, duration_b_s: float, offset_b_s: float = 0.0) -> float:
    """Gemeinsame vergleichbare Laufzeit bei einem optionalen Offset von Datei B."""
    duration_a = max(0.0, float(duration_a_s or 0.0))
    duration_b = max(0.0, float(duration_b_s or 0.0))
    offset = float(offset_b_s or 0.0)
    if offset >= 0:
        return max(0.0, min(duration_a, duration_b - offset))
    return max(0.0, min(duration_a + offset, duration_b))


def comparison_segment_starts(start_s: float, offset_b_s: float = 0.0) -> tuple[float, float]:
    """Liefert synchronisierte Startzeiten für A/B. Negative B-Offsets verschieben A nach vorn."""
    start = max(0.0, float(start_s or 0.0))
    offset = float(offset_b_s or 0.0)
    if offset >= 0:
        return start, start + offset
    return start - offset, start


def quality_comparison_assessment(
    *,
    average_vmaf: float | None,
    average_ssim: float | None,
    size_a_bytes: int,
    size_b_bytes: int,
) -> str:
    """Konservative Bewertung von B relativ zu A, ohne einen absoluten Qualitätsgewinner vorzutäuschen."""
    similarity = "Ähnlichkeit nicht quantifizierbar"
    if average_vmaf is not None:
        if average_vmaf >= 97.0:
            similarity = "B ist visuell sehr nah an A"
        elif average_vmaf >= 93.0:
            similarity = "B liegt visuell nah an A"
        elif average_vmaf >= 85.0:
            similarity = "B zeigt messbare Unterschiede zu A"
        else:
            similarity = "B unterscheidet sich deutlich von A"
    elif average_ssim is not None:
        if average_ssim >= 0.995:
            similarity = "B ist strukturell sehr nah an A"
        elif average_ssim >= 0.985:
            similarity = "B liegt strukturell nah an A"
        elif average_ssim >= 0.95:
            similarity = "B zeigt messbare strukturelle Unterschiede zu A"
        else:
            similarity = "B unterscheidet sich strukturell deutlich von A"

    a = max(0, int(size_a_bytes or 0))
    b = max(0, int(size_b_bytes or 0))
    if a > 0 and b > 0:
        delta_pct = (b - a) / a * 100.0
        if delta_pct <= -0.5:
            size_note = f"B ist {abs(delta_pct):.1f}% kleiner"
        elif delta_pct >= 0.5:
            size_note = f"B ist {delta_pct:.1f}% größer"
        else:
            size_note = "beide Dateien sind nahezu gleich groß"
        return f"{similarity}; {size_note}. A ist die gewählte Referenz, kein automatisch bestimmter Qualitätsgewinner."
    return f"{similarity}. A ist die gewählte Referenz, kein automatisch bestimmter Qualitätsgewinner."


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def seconds_to_label(seconds: float) -> str:
    total = max(0, int(round(float(seconds))))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h:
        return f"{h:02d}-{m:02d}-{s:02d}"
    return f"{m:02d}-{s:02d}"


def parse_time_value(text: str, duration_s: float | None = None) -> float:
    value = str(text or "").strip()
    if not value:
        return 0.0
    if value.endswith("%"):
        pct = _safe_float(value[:-1], 0.0)
        return max(0.0, (duration_s or 0.0) * pct / 100.0)
    parts = value.split(":")
    if len(parts) == 3:
        return (
            _safe_float(parts[0]) * 3600.0
            + _safe_float(parts[1]) * 60.0
            + _safe_float(parts[2])
        )
    if len(parts) == 2:
        return _safe_float(parts[0]) * 60.0 + _safe_float(parts[1])
    return _safe_float(value)


def parse_quality_segments(
    text: str,
    *,
    duration_s: float,
    default_duration_s: float,
) -> list[QualitySegment]:
    """Parst manuelle Bereiche wie ``10%+20`` oder ``00:05:00+30``."""
    segments: list[QualitySegment] = []
    raw_text = str(text or "").replace(";", "\n").replace(",", "\n")
    for idx, raw in enumerate(raw_text.splitlines(), start=1):
        item = raw.strip()
        if not item:
            continue
        if "+" in item:
            start_txt, dur_txt = item.split("+", 1)
        else:
            start_txt, dur_txt = item, str(default_duration_s)
        start = parse_time_value(start_txt, duration_s)
        dur = max(1.0, parse_time_value(dur_txt, duration_s))
        if duration_s > 0:
            start = min(max(0.0, start), max(0.0, duration_s - 1.0))
            dur = min(dur, max(1.0, duration_s - start))
        label = f"{idx:02d}_{seconds_to_label(start)}_{int(round(dur))}s"
        segments.append(QualitySegment(start, dur, label))
    return segments


def automatic_quality_segments(
    *,
    duration_s: float,
    count: int,
    segment_duration_s: float,
) -> list[QualitySegment]:
    count = max(1, min(20, int(count or 1)))
    segment_duration_s = max(1.0, float(segment_duration_s or 1.0))
    if duration_s <= 0:
        return [
            QualitySegment(
                start_s=0.0,
                duration_s=segment_duration_s,
                label=f"{idx:02d}_00-00_{int(round(segment_duration_s))}s",
            )
            for idx in range(1, count + 1)
        ]

    usable_end = max(1.0, duration_s - segment_duration_s)
    step = usable_end / float(count + 1)
    segments: list[QualitySegment] = []
    for idx in range(1, count + 1):
        start = min(usable_end, max(0.0, step * idx))
        dur = min(segment_duration_s, max(1.0, duration_s - start))
        segments.append(
            QualitySegment(
                start_s=start,
                duration_s=dur,
                label=f"{idx:02d}_{seconds_to_label(start)}_{int(round(dur))}s",
            )
        )
    return segments


def quality_output_name(input_path: str, run: QualityTestRun, segment: QualitySegment) -> str:
    stem = Path(input_path).stem
    run_name = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in run.name.strip())
    codec = (run.codec or "video").lower()
    encoder = (run.encoder or "enc").lower()
    return f"{stem}__{segment.label}__{run_name or codec}_{encoder}.mkv"


def parse_extra_args(text: str) -> list[str]:
    """Kleine Shell-ähnliche Zerlegung für zusätzliche FFmpeg-Argumente."""
    import shlex

    raw = str(text or "").strip()
    if not raw:
        return []
    try:
        return shlex.split(raw, posix=False)
    except Exception:
        return raw.split()


def quality_run_from_dict(data: dict) -> QualityTestRun:
    raw_encoder_options = data.get("encoder_options")
    return QualityTestRun(
        name=str(data.get("name") or "Testlauf"),
        codec=normalize_target_codec(data.get("codec") or "h265"),
        encoder=str(data.get("encoder") or "cpu").lower(),
        quality=max(0, min(63, int(_safe_float(data.get("quality"), 23)))),
        preset=str(data.get("preset") or "medium"),
        pix_fmt=str(data.get("pix_fmt") or "10-bit"),
        scale=str(data.get("scale") or "original"),
        extra_args=str(data.get("extra_args") or ""),
        encoder_options=dict(raw_encoder_options) if isinstance(raw_encoder_options, dict) else {},
    )
