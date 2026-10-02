# -*- coding: utf-8 -*-
"""Discovery of existing companion files for Move-Only jobs.

The conversion pipeline already knows generated companions via its artifact
registry.  Move-Only starts from arbitrary existing media, so those companions
must be discovered from the source directory before MoveThread starts.
"""
from __future__ import annotations

from pathlib import Path

_SUBTITLE_EXTENSIONS = frozenset({".srt", ".ass", ".ssa", ".sup", ".sub", ".idx", ".vtt"})


def discover_move_companions(video_path: str | Path) -> list[str]:
    """Return conservative sidecars belonging to *video_path*.

    Only companions that clearly share the video's stem are selected.  This
    deliberately avoids broad wildcard matching that could move a sidecar of a
    neighbouring episode/movie.  ``<stem>.trickplay`` is included as a folder.
    """
    video = Path(video_path)
    parent = video.parent
    stem_cf = video.stem.casefold()
    found: list[Path] = []

    try:
        entries = list(parent.iterdir())
    except OSError:
        return []

    trickplay_name = f"{video.stem}.trickplay".casefold()
    exact_nfo = f"{video.stem}.nfo".casefold()

    for entry in entries:
        name_cf = entry.name.casefold()
        if entry.is_dir():
            if name_cf == trickplay_name:
                found.append(entry)
            continue
        if not entry.is_file():
            continue

        if name_cf == exact_nfo:
            found.append(entry)
            continue

        suffix = entry.suffix.casefold()
        if suffix not in _SUBTITLE_EXTENSIONS:
            continue
        sidecar_stem = entry.stem.casefold()
        if sidecar_stem == stem_cf or sidecar_stem.startswith(stem_cf + "."):
            found.append(entry)

    return [str(path) for path in sorted(found, key=lambda p: p.name.casefold())]


def merge_discovered_move_companions(
    files: list[str] | tuple[str, ...],
    existing: dict[str, list[str]] | None = None,
) -> dict[str, list[str]]:
    """Merge discovered source companions with an existing companion map."""
    result = {str(key): list(values or []) for key, values in (existing or {}).items()}
    for file_path in files:
        key = str(file_path)
        merged = list(result.get(key, []))
        seen = {str(Path(value).absolute()).casefold() for value in merged}
        for companion in discover_move_companions(key):
            normalized = str(Path(companion).absolute()).casefold()
            if normalized not in seen:
                merged.append(companion)
                seen.add(normalized)
        if merged:
            result[key] = merged
    return result


__all__ = ["discover_move_companions", "merge_discovered_move_companions"]
