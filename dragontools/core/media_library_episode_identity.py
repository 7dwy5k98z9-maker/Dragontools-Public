from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .path_syntax import path_compare_key, user_path_name, user_path_parent
from .media_library_utils import _int_or_none, _normalize_title

_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
_SEASON_DIR_RE = re.compile(r"^(?:staffel|season|saison)\s*\d+\b", re.IGNORECASE)
_SPECIAL_DIR_NAMES = {"special", "specials", "extra", "extras"}


@dataclass(frozen=True)
class EpisodeSeriesIdentity:
    """Series identity used only for destructive episode replacement decisions.

    ``normalized_title`` intentionally remains compatible with the search/index
    normalization used by the media library.  It is *not* sufficient on its own
    for destructive matching because that normalization removes release years.
    ``series_root_key`` and ``year`` therefore provide the safety boundary.
    """

    normalized_title: str
    year: int | None
    series_root_key: str


def _year_from_text(value: str | None) -> int | None:
    match = _YEAR_RE.search(str(value or ""))
    return int(match.group(1)) if match else None


def _is_season_directory_name(name: str) -> bool:
    text = str(name or "").strip()
    return bool(_SEASON_DIR_RE.match(text)) or text.casefold() in _SPECIAL_DIR_NAMES


def episode_series_root(path: str) -> str:
    """Return the logical series folder for an episode path, host-independently."""
    parent = user_path_parent(path)
    if not parent:
        return ""
    if _is_season_directory_name(user_path_name(parent)):
        return user_path_parent(parent) or parent
    return parent


def episode_series_identity(item: dict[str, Any]) -> EpisodeSeriesIdentity:
    path = str(item.get("path") or item.get("filename") or "")
    root = episode_series_root(path)
    normalized_title = str(
        item.get("normalized_title")
        or _normalize_title(item.get("series_title") or user_path_name(root))
        or ""
    )
    year = _int_or_none(item.get("year"))
    if year is None:
        year = _year_from_text(user_path_name(root))
    return EpisodeSeriesIdentity(
        normalized_title=normalized_title,
        year=year,
        series_root_key=path_compare_key(root) if root else "",
    )


def same_series_for_episode_replacement(
    left: EpisodeSeriesIdentity,
    right: EpisodeSeriesIdentity,
) -> bool:
    """Fail-safe equality for destructive episode replacement.

    Exact logical series-root equality is authoritative.  A title based fallback
    is allowed only when both sides also carry the same explicit release year.
    If one side has no year and the roots differ, the function deliberately
    returns False; callers may still deactivate an explicitly supplied old path.
    """
    if left.series_root_key and right.series_root_key and left.series_root_key == right.series_root_key:
        return True
    if not left.normalized_title or left.normalized_title != right.normalized_title:
        return False
    return left.year is not None and right.year is not None and left.year == right.year


__all__ = [
    "EpisodeSeriesIdentity",
    "episode_series_identity",
    "episode_series_root",
    "same_series_for_episode_replacement",
]
