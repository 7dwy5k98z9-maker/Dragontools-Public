# -*- coding: utf-8 -*-
from __future__ import annotations


def luma(frame: bytes, pixel_index: int) -> float:
    offset = pixel_index * 3
    try:
        return frame[offset] * 0.2126 + frame[offset + 1] * 0.7152 + frame[offset + 2] * 0.0722
    except IndexError:
        return 0.0


def mean_neighbor_diff(frame: bytes, width: int, height: int) -> float:
    if width <= 1 or height <= 1:
        return 0.0
    total = 0.0
    count = 0
    for y in range(height):
        row = y * width
        for x in range(width - 1):
            a = luma(frame, row + x)
            b = luma(frame, row + x + 1)
            total += abs(a - b)
            count += 1
    for y in range(height - 1):
        row = y * width
        next_row = (y + 1) * width
        for x in range(width):
            a = luma(frame, row + x)
            b = luma(frame, next_row + x)
            total += abs(a - b)
            count += 1
    return total / max(1, count)


def analyze_frame(frame: bytes, width: int, height: int) -> tuple[bool, str]:
    pixel_count = max(1, len(frame) // 3)
    channels = len(frame)
    mean = sum(frame) / max(1, channels)
    variance = sum((value - mean) ** 2 for value in frame) / max(1, channels)

    r_mean = sum(frame[0::3]) / pixel_count
    g_mean = sum(frame[1::3]) / pixel_count
    b_mean = sum(frame[2::3]) / pixel_count
    channel_delta = max(r_mean, g_mean, b_mean) - min(r_mean, g_mean, b_mean)

    neighbor_diff = mean_neighbor_diff(frame, width, height)
    if variance < 8.0 and (mean < 12.0 or mean > 243.0):
        return True, "nahezu leer/schwarz/weiß"
    if neighbor_diff < 1.5 and channel_delta > 28.0:
        return True, "einfarbige auffällige Fläche"
    if neighbor_diff > 58.0 and channel_delta > 22.0 and variance > 2200.0:
        return True, "starkes Pixelrauschen"
    return False, ""


def most_common_reason(reasons: list[str]) -> str:
    if not reasons:
        return ""
    counts: dict[str, int] = {}
    for reason in reasons:
        counts[reason] = counts.get(reason, 0) + 1
    return max(counts.items(), key=lambda item: item[1])[0]


__all__ = ["analyze_frame", "luma", "mean_neighbor_diff", "most_common_reason"]
