"""One global timestamp grid, divided into bounded raw-frame windows."""
import math
from .strict_numbers import positive_integer


def sampling_windows(start_s, duration_s, fps, width, height, byte_budget):
    start, duration, rate = float(start_s), float(duration_s), float(fps)
    if not all(math.isfinite(v) for v in (start, duration, rate)) or duration <= 0 or rate <= 0:
        raise ValueError("Bildanalyse benötigt endliche Zeit- und positive FPS-Werte.")
    start = max(0.0, start)
    frame_size = positive_integer(width) * positive_integer(height)
    frame_budget = int(byte_budget) // frame_size
    if frame_budget < 1:
        raise ValueError("Analysebild überschreitet die Speichergrenze.")
    total = math.ceil(duration * rate - 1e-9)
    for first in range(0, total, frame_budget):
        count = min(frame_budget, total - first)
        offset = first / rate
        yield first, start + offset, min(count / rate, duration - offset), count
