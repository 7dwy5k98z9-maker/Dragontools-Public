# -*- coding: utf-8 -*-
"""Application/bundle resource roots and known external-tool directories."""
from __future__ import annotations

import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
BASE = (
    Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2])).resolve()
    if FROZEN
    else Path(__file__).resolve().parents[2]
)
EXE_DIR = Path(sys.executable).parent.resolve() if FROZEN else BASE

PROGRAMME_DIR = "Programme"
THIRD_PARTY_DIR = "third_party"
THIRD_PARTY_TOOL_DIRS = (
    Path(THIRD_PARTY_DIR) / "FFmpeg",
    Path(THIRD_PARTY_DIR) / "MKVToolNix",
    Path(THIRD_PARTY_DIR) / "MakeMKV",
    Path(THIRD_PARTY_DIR) / "GPAC",
    Path(THIRD_PARTY_DIR) / "HandBrake",
    Path(THIRD_PARTY_DIR) / "Mediainfo",
    Path(THIRD_PARTY_DIR) / "dovi_tool",
    Path(THIRD_PARTY_DIR) / "hdr10plus_tool",
    Path(THIRD_PARTY_DIR) / "rmts",
)
PROGRAMME_TOOL_DIRS = (
    Path(PROGRAMME_DIR) / "FFmpeg",
    Path(PROGRAMME_DIR) / "mkvtoolnix",
    Path(PROGRAMME_DIR) / "MakeMKV",
    Path(PROGRAMME_DIR) / "GPAC",
    Path(PROGRAMME_DIR) / "handbrake",
    Path(PROGRAMME_DIR) / "mediainfo",
    Path(PROGRAMME_DIR) / "dovi_tool",
    Path(PROGRAMME_DIR) / "hdr10plus_tool",
    Path(PROGRAMME_DIR) / "rmts",
)
MKV_DIR = f"{PROGRAMME_DIR}/mkvtoolnix"
RMTS_DIR = f"{PROGRAMME_DIR}/rmts"
HB_DIR = f"{PROGRAMME_DIR}/handbrake"
MEDIAINFO_DIR = f"{PROGRAMME_DIR}/mediainfo"
ICON_DIR = "icon"
IMAGES_DIR = "Bilder"


def resource_path(rel: str, *, base: Path | None = None) -> str:
    """Return an absolute path to a bundled/project resource."""
    root = BASE if base is None else Path(base)
    return str((root / rel).resolve())


def known_tool_dirs(*, base: Path | None = None, exe_dir: Path | None = None) -> list[Path]:
    """Return all deterministic bundle/dev locations that may contain tools."""
    base_root = BASE if base is None else Path(base)
    exe_root = EXE_DIR if exe_dir is None else Path(exe_dir)
    candidates: list[Path] = [base_root, exe_root]
    relative_dirs = (
        Path(PROGRAMME_DIR),
        Path(THIRD_PARTY_DIR),
        *PROGRAMME_TOOL_DIRS,
        *THIRD_PARTY_TOOL_DIRS,
    )
    for rel in relative_dirs:
        candidates.extend((base_root / rel, exe_root / rel, exe_root / "Daten" / rel))
    return candidates


__all__ = [
    "FROZEN", "BASE", "EXE_DIR", "PROGRAMME_DIR", "THIRD_PARTY_DIR",
    "THIRD_PARTY_TOOL_DIRS", "PROGRAMME_TOOL_DIRS", "MKV_DIR", "RMTS_DIR",
    "HB_DIR", "MEDIAINFO_DIR", "ICON_DIR", "IMAGES_DIR", "resource_path",
    "known_tool_dirs",
]
