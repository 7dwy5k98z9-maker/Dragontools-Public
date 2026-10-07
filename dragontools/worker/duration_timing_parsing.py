# -*- coding: utf-8 -*-
"""Primitive parsing helpers for duration/timing analysis."""
from __future__ import annotations

from fractions import Fraction
import math
from ..core.media_duration import stream_duration as _stream_duration
from ..core.strict_numbers import nonnegative_integer

from .duration_repair_models import _COMMON_FRAME_RATES


def parse_duration_tag(value) -> float | None:
    if value in (None, "", "N/A"):
        return None
    text = str(value).strip()
    if ":" not in text:
        try:
            number = float(text.replace(",", "."))
            return number if math.isfinite(number) and number >= 0 else None
        except (TypeError, ValueError):
            return None
    try:
        parts = text.split(":")
        if len(parts) != 3:
            return None
        hours = nonnegative_integer(parts[0])
        minutes = nonnegative_integer(parts[1])
        seconds = float(parts[2].replace(",", "."))
        if minutes >= 60 or not math.isfinite(seconds) or not 0 <= seconds < 60:
            return None
        return hours * 3600.0 + minutes * 60.0 + seconds
    except (TypeError, ValueError):
        return None


def parse_seconds(value) -> float | None:
    if value in (None, "", "N/A"):
        return None
    try:
        number = float(str(value).replace(",", "."))
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return parse_duration_tag(value)


def parse_mediainfo_duration(value) -> float | None:
    from ..core.media_metadata import _parse_mediainfo_duration_s
    return _parse_mediainfo_duration_s(value)


def parse_int(value) -> int | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return nonnegative_integer(value)
    except (TypeError, ValueError):
        return None


def nearest_common_rate(value: float) -> Fraction | None:
    for rate in _COMMON_FRAME_RATES:
        if abs(float(rate) - value) <= 0.001:
            return rate
    return None


def nearest_common_rate_loose(value: float) -> Fraction | None:
    for rate in _COMMON_FRAME_RATES:
        if abs(float(rate) - value) <= max(0.005, float(rate) * 0.001):
            return rate
    return None


def parse_fraction(value) -> Fraction | None:
    if value in (None, "", "N/A", "0/0"):
        return None
    text = str(value).strip().replace(",", ".")
    try:
        if "/" in text:
            num, den = text.split("/", 1)
            fraction = Fraction(int(num), int(den))
        else:
            numeric = float(text)
            fraction = nearest_common_rate(numeric) or Fraction(text).limit_denominator(1001)
        if fraction <= 0:
            return None
        return nearest_common_rate(float(fraction)) or fraction
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def choose_frame_rate(avg: Fraction | None, real: Fraction | None) -> Fraction | None:
    if avg is not None and avg > 0:
        return avg
    if real is not None and real > 0:
        return real
    return None


def max_known(values: list[float | None]) -> float | None:
    known = [float(value) for value in values if value is not None and math.isfinite(value) and value > 0]
    return max(known) if known else None


def stream_duration(stream: dict) -> float | None:
    return _stream_duration(stream)


__all__ = [
    "parse_duration_tag", "parse_seconds", "parse_mediainfo_duration", "parse_int",
    "parse_fraction", "nearest_common_rate", "nearest_common_rate_loose",
    "choose_frame_rate", "max_known", "stream_duration",
]
