# -*- coding: utf-8 -*-
"""Backward-compatible path facade.

Path syntax, storage defaults, bundle roots and tool discovery now have separate
owners. Existing third-party imports can continue using ``dragontools.core.paths``.
New production code should import the dedicated module directly.
"""
from __future__ import annotations

from pathlib import Path

from .path_syntax import *  # noqa: F401,F403
from .path_defaults import *  # noqa: F401,F403
from .resource_paths import FROZEN, BASE, EXE_DIR, PROGRAMME_DIR, THIRD_PARTY_DIR, THIRD_PARTY_TOOL_DIRS, PROGRAMME_TOOL_DIRS, MKV_DIR, RMTS_DIR, HB_DIR, MEDIAINFO_DIR, ICON_DIR, IMAGES_DIR
from .tool_paths import ToolPathSettingsProvider, ToolPaths, get_tool_paths, invalidate_tool_paths, find_tool_in_settings
from . import resource_paths as _resources
from . import tool_paths as _tools


def resource_path(rel: str) -> str:
    """Compatibility wrapper honoring monkeypatched ``paths.BASE`` in tests/tools."""
    return _resources.resource_path(rel, base=BASE)


def _known_tool_dirs() -> list[Path]:
    return _resources.known_tool_dirs(base=BASE, exe_dir=EXE_DIR)


def extend_path(extra: list[Path] | None = None) -> None:
    """Compatibility wrapper honoring facade root overrides."""
    _tools.extend_path(extra=extra, base=BASE, exe_dir=EXE_DIR)


def find_tool(name: str, *alt_names: str) -> str:
    """Compatibility wrapper honoring facade root overrides."""
    return _tools.find_tool(name, *alt_names, base=BASE, exe_dir=EXE_DIR)


__all__ = [name for name in globals() if not name.startswith("_")]
