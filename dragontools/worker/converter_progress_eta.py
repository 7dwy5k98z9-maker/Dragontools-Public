"""Finite progress estimates, independent of FFmpeg protocol parsing."""
from math import isfinite


def progress_percent(value, total) -> int:
    bounded = min(max(0, value), total)
    return int(bounded / total * 100)


def estimate_eta(duration_ms, output_ms, speed, elapsed_s):
    if not duration_ms or output_ms <= 0:
        return None
    output_ms = min(output_ms, duration_ms)
    remaining = max(0.0, (duration_ms - output_ms) / 1000.0)
    if not speed or speed <= 0:
        speed = max(0.001, output_ms / 1000.0) / elapsed_s
    value = remaining / speed if speed > 0 else None
    return value if value is not None and isfinite(value) else None


def progress_from_eta(percent, *, eta_s, elapsed_s, output_ms):
    if eta_s is None or elapsed_s < 15 or output_ms < 30_000:
        return percent
    denominator = elapsed_s + max(0.0, eta_s)
    return min(99, progress_percent(elapsed_s, denominator)) if denominator > 0 else percent
