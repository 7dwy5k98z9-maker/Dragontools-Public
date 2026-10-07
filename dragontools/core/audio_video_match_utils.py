# -*- coding: utf-8 -*-
from __future__ import annotations

from .audio_video_match_models import CutRegion
import math

def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value in (None, "", "N/A"):
            return default
        return float(str(value).replace(",", "."))
    except Exception:
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def format_seconds(value: float) -> str:
    seconds = max(0.0, float(value or 0.0))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds - h * 3600 - m * 60
    if h:
        return f"{h:02d}:{m:02d}:{s:05.2f}"
    return f"{m:02d}:{s:05.2f}"


def parse_timecode(text: str, *, duration_s: float | None = None) -> float:
    value = str(text or "").strip().replace(",", ".")
    if not value:
        return 0.0
    if value.endswith("%"):
        result = float(duration_s or 0.0) * _time_component(value[:-1]) / 100.0
        if not math.isfinite(result) or result < 0:
            raise ValueError("Ungültige Prozent-Zeitangabe.")
        return result
    parts = value.split(":")
    if len(parts) == 3:
        return _time_component(parts[0]) * 3600.0 + _time_component(parts[1]) * 60.0 + _time_component(parts[2])
    if len(parts) == 2:
        return _time_component(parts[0]) * 60.0 + _time_component(parts[1])
    return _time_component(value)


def _time_component(value):
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError("Zeitangaben müssen endlich und nicht negativ sein.")
    return number


def parse_cut_regions(text: str, *, duration_s: float | None = None) -> list[CutRegion]:
    regions: list[CutRegion] = []
    for raw in str(text or "").replace("\n", ";").split(";"):
        item = raw.strip()
        if not item:
            continue
        if "-" not in item:
            raise ValueError(f"Ungültiger Bereich: {item}")
        start_txt, end_txt = item.split("-", 1)
        start = parse_timecode(start_txt, duration_s=duration_s)
        end = parse_timecode(end_txt, duration_s=duration_s)
        if end <= start:
            raise ValueError(f"Bereich endet nicht nach dem Start: {item}")
        if duration_s and duration_s > 0:
            start = _clamp(start, 0.0, duration_s)
            end = _clamp(end, 0.0, duration_s)
        if end <= start:
            raise ValueError(f"Bereich liegt außerhalb der Laufzeit: {item}")
        regions.append(CutRegion(start_s=start, end_s=end))
    regions.sort(key=lambda r: (r.start_s, r.end_s))
    return regions
