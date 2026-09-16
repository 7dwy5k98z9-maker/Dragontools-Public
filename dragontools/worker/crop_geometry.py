# -*- coding: utf-8 -*-
"""Deterministic crop geometry helpers.

The encoder path targets 4:2:0 video. For that chroma layout, crop origin and
output dimensions should be even.  Normalisation therefore expands an odd
crop outward by at most one pixel per affected edge whenever the source frame
allows it.  This preserves detected picture content instead of silently
cutting another pixel from the active image.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CropRect:
    width: int
    height: int
    x: int
    y: int

    @property
    def area(self) -> int:
        return max(0, self.width) * max(0, self.height)

    def as_filter(self) -> str:
        return f"crop={self.width}:{self.height}:{self.x}:{self.y}"

    def edges(self, source_width: int, source_height: int) -> tuple[int, int, int, int]:
        return (
            self.x,
            max(0, int(source_width) - self.x - self.width),
            self.y,
            max(0, int(source_height) - self.y - self.height),
        )


def parse_crop_filter(value: str | None) -> CropRect | None:
    """Parse ``crop=W:H:X:Y`` into a :class:`CropRect`."""
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith("crop="):
        text = text[5:]
    parts = text.split(":")
    if len(parts) < 4:
        return None
    try:
        width, height, x, y = (
            int(float(part.strip().replace(",", "."))) for part in parts[:4]
        )
    except (TypeError, ValueError):
        return None
    if min(width, height) <= 0 or min(x, y) < 0:
        return None
    return CropRect(width, height, x, y)


def _normalise_axis(*, start: int, size: int, limit: int) -> tuple[int, int]:
    """Return an even ``(start, size)`` while preserving picture content.

    The preferred operation is expansion: an odd start moves one pixel toward
    zero and an odd end moves one pixel outward. Only if the source boundary
    itself prevents outward expansion is the end moved inward by one pixel.
    """
    start = int(start)
    size = int(size)
    limit = int(limit)
    end = start + size
    if limit <= 0 or start < 0 or size <= 0 or end > limit:
        raise ValueError(
            f"Crop ausserhalb der Quelle: start={start}, size={size}, limit={limit}"
        )

    normal_start = start - (start % 2)
    normal_end = end + (end % 2)

    if normal_end > limit:
        # This only matters for an odd source boundary. Prefer keeping the
        # start expanded and trim the far edge by one pixel as the safe
        # fallback. Typical 4:2:0 sources have an even limit, so the normal
        # path above expands 1607 -> 1608.
        normal_end = end - (end % 2)

    if normal_end <= normal_start:
        raise ValueError(
            f"Crop kann nicht auf gerade 4:2:0-Geometrie normalisiert werden: "
            f"start={start}, size={size}, limit={limit}"
        )

    normal_size = normal_end - normal_start
    if normal_start % 2 or normal_size % 2:
        raise ValueError(
            f"Interner Crop-Alignmentfehler: start={normal_start}, size={normal_size}"
        )
    return normal_start, normal_size


def normalize_crop_rect(
    rect: CropRect,
    *,
    source_width: int,
    source_height: int,
) -> CropRect:
    """Normalize a crop for 4:2:0 encoding.

    Odd geometry is expanded outward by one pixel where possible. This means
    an active height of 1607 normally becomes 1608 rather than 1606. The
    returned rectangle is always inside the source frame and has even x/y and
    even width/height.
    """
    x, width = _normalise_axis(
        start=rect.x,
        size=rect.width,
        limit=int(source_width),
    )
    y, height = _normalise_axis(
        start=rect.y,
        size=rect.height,
        limit=int(source_height),
    )
    return CropRect(width=width, height=height, x=x, y=y)


def normalize_crop_filter(
    value: str | None,
    *,
    source_width: int,
    source_height: int,
) -> str | None:
    rect = parse_crop_filter(value)
    if rect is None:
        return None
    return normalize_crop_rect(
        rect,
        source_width=source_width,
        source_height=source_height,
    ).as_filter()
