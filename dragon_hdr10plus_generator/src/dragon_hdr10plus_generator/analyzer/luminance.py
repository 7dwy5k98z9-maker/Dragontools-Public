from __future__ import annotations

import math

# SMPTE ST 2084 constants (PQ), normalized code value <-> absolute luminance.
_M1 = 2610.0 / 16384.0
_M2 = 2523.0 / 32.0
_C1 = 3424.0 / 4096.0
_C2 = 2413.0 / 128.0
_C3 = 2392.0 / 128.0
_PEAK_NITS = 10000.0


def pq_eotf(code_value: float) -> float:
    """Convert normalized PQ signal [0,1] to absolute luminance in cd/m²."""
    value = min(1.0, max(0.0, float(code_value)))
    p = value ** (1.0 / _M2)
    numerator = max(p - _C1, 0.0)
    denominator = _C2 - _C3 * p
    if denominator <= 0.0:
        return _PEAK_NITS
    return _PEAK_NITS * (numerator / denominator) ** (1.0 / _M1)


def pq_oetf(luminance_nits: float) -> float:
    """Convert absolute luminance in cd/m² to normalized PQ signal [0,1]."""
    normalized = min(1.0, max(0.0, float(luminance_nits) / _PEAK_NITS))
    p = normalized ** _M1
    encoded = ((_C1 + _C2 * p) / (1.0 + _C3 * p)) ** _M2
    return min(1.0, max(0.0, encoded if math.isfinite(encoded) else 0.0))


__all__ = ["pq_eotf", "pq_oetf"]
