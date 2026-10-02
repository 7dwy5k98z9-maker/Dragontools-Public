"""Explicit timestamp policy for complete, jointly muxed FFmpeg outputs."""
from __future__ import annotations

from pathlib import Path


def build_output_timestamp_args(container: str | Path, *, role: str = "final") -> list[str]:
    """Shift all streams together at the mux boundary, preserving A/V/S offsets.

    Do NOT apply to separately extracted audio/subtitles, raw bitstreams or
    repair candidates: independently zeroing donors would destroy their common
    origin. No copyts, genpts, igndts or per-stream timestamp filters are added.
    """
    if role not in {"final", "donor", "elementary", "repair"}:
        raise ValueError(f"Unknown timestamp output role: {role}")
    suffix = str(container).lower()
    kind = Path(suffix).suffix.lstrip(".") or suffix.lstrip(".")
    if role == "final" and kind in {"mkv", "matroska", "mp4", "mov", "m4v"}:
        return ["-avoid_negative_ts", "make_zero"]
    return []
