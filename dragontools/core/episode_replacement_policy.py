# -*- coding: utf-8 -*-
"""Policy helpers for SxxExx-only episode replacement conflicts."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from .move_conflicts import episode_identity_for_path
from .settings_storage import DEFAULT_EPISODE_REPLACEMENT_MODE, EPISODE_REPLACEMENT_MODES


def normalize_episode_replacement_mode(value: str | None) -> str:
    mode = str(value or "").strip().lower()
    return mode if mode in EPISODE_REPLACEMENT_MODES else DEFAULT_EPISODE_REPLACEMENT_MODE


def identity_only_episode_conflicts(dst_p: Path, episode_conflicts: list[Path]) -> list[Path]:
    """Return conflicts that match only by episode identity, not by target stem."""
    target_stem = Path(dst_p).stem.casefold()
    return [Path(path) for path in episode_conflicts if Path(path).stem.casefold() != target_stem]


def build_episode_replacement_prompt(dst_p: Path, conflicts: list[Path]) -> dict:
    identity = episode_identity_for_path(dst_p)
    return {
        "type": "confirm_episode_replacement",
        "target_path": str(dst_p),
        "target_name": Path(dst_p).name,
        "conflict_paths": [str(path) for path in conflicts],
        "conflict_names": [Path(path).name for path in conflicts],
        "episode_label": identity.label if identity else "",
        "series": identity.series if identity else "",
        "season": identity.season if identity else None,
        "episodes": list(identity.episodes) if identity else [],
    }


def allow_identity_replacement(
    mode: str,
    *,
    dst_p: Path,
    conflicts: list[Path],
    ask: Callable[[dict], bool] | None,
) -> bool:
    normalized = normalize_episode_replacement_mode(mode)
    if normalized == "auto":
        return True
    if normalized == "never":
        return False
    if ask is None:
        return False
    return bool(ask(build_episode_replacement_prompt(dst_p, conflicts)))
