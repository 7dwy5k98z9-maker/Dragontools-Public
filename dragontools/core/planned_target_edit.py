# -*- coding: utf-8 -*-
"""Helpers for safely editing planned move targets after conversion start.

The GUI may rebase a series to another series root while preserving the
season-folder routing, or replace a film target with an explicitly selected
complete destination folder.  This module stays Qt-free so the behavior is
fully regression-testable.
"""
from __future__ import annotations

import re
from typing import Any

from ..rules.move_rules import parse_series_match_details, planned_target_dir
from .path_syntax import join_user_path, user_path_name, user_path_parent

_SEASON_DIR_RE = re.compile(r"^Staffel\s+(\d{1,3})$", re.IGNORECASE)
_SPECIAL_DIR_NAMES = {"specials", "special", "staffel 00", "season 00", "season 0"}


def infer_series_season(path: str, planned_entry: Any = None) -> int | None:
    """Return the season for a queue item, including EP-only preflight targets.

    Normal SxxEyy/EyySxx names are parsed from the source path.  EP-only names
    intentionally contain no season; after preflight their planned target does,
    so the existing target's final folder is used as the authoritative fallback.
    """
    parsed = parse_series_match_details(user_path_name(path))
    if parsed and parsed.get("season") is not None:
        try:
            return int(parsed["season"])
        except (TypeError, ValueError):
            pass

    target = planned_target_dir(planned_entry)
    if not target:
        return None
    leaf = user_path_name(target).strip()
    if leaf.casefold() in _SPECIAL_DIR_NAMES:
        return 0
    match = _SEASON_DIR_RE.fullmatch(leaf)
    return int(match.group(1)) if match else None


def target_kind(path: str, planned_entry: Any = None) -> str:
    """Classify a target edit as ``series`` or ``film``."""
    return "series" if infer_series_season(path, planned_entry) is not None else "film"


def series_root_from_target(planned_entry: Any) -> str | None:
    """Return the current series root when a planned target ends in a season folder."""
    target = planned_target_dir(planned_entry)
    if not target:
        return None
    leaf = user_path_name(target).strip()
    if leaf.casefold() in _SPECIAL_DIR_NAMES or _SEASON_DIR_RE.fullmatch(leaf):
        return user_path_parent(target)
    return None


def rebase_series_target(path: str, planned_entry: Any, new_series_root: str) -> str:
    """Move a series plan to *new_series_root* while preserving season routing."""
    root = str(new_series_root or "").strip()
    if not root:
        raise ValueError("Der neue Serien-Zielordner ist leer.")
    season = infer_series_season(path, planned_entry)
    if season is None:
        raise ValueError(f"Staffel konnte für '{user_path_name(path)}' nicht bestimmt werden.")
    folder = "Specials" if season == 0 else f"Staffel {season:02d}"
    return join_user_path(root, folder)
