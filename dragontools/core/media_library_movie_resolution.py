from __future__ import annotations

import sqlite3
from typing import Iterable

from .media_library_path_mappings import _area_from_root, _area_label
from .media_library_types import PathMapping, describe_series_path_resolution
from .media_library_utils import _normalize_title
from .media_library_series_resolution import _year_suffix_from_text
from .path_syntax import normalize_user_path, path_compare_key, user_path_name, user_path_parent


def movie_row_matches(row: sqlite3.Row, root: str, target_norms: tuple[str, ...]) -> bool:
    names = (
        str(row["title"] or ""),
        str(row["original_title"] or ""),
        str(row["filename"] or ""),
        user_path_name(root),
    )
    row_norms = {_normalize_title(name) for name in names if name}
    return bool(set(target_norms).intersection(row_norms))


def movie_candidate_year(row: sqlite3.Row, root: str) -> int | None:
    folder_year = _year_suffix_from_text(user_path_name(root))
    if folder_year is not None:
        return folder_year
    try:
        return int(row["year"]) if row["year"] else None
    except (TypeError, ValueError):
        return None


def unusable_movie_result(
    *,
    root: str,
    mapped_root: str,
    reason: str,
    matched_base: tuple[str, str] | None,
    movie_title: str,
    stored_mappings: list[PathMapping],
    current_mappings: list[PathMapping],
) -> dict[str, str]:
    area = _area_from_root(root, [*stored_mappings, *current_mappings])
    base_type = matched_base[1] if matched_base else _area_label(area)
    prefix = "Mediathek-Filmtreffer ist aktuell nicht erreichbar"
    if base_type:
        prefix += f" (Bereich {base_type})"
    message = f"{prefix}: {mapped_root}"
    database_path = normalize_user_path(root)
    if database_path and path_compare_key(database_path) != path_compare_key(mapped_root):
        message += f" | DB-Pfad: {database_path}"
    if reason:
        message += f" | Grund: {reason}"
    return {
        "movie_dir": "",
        "base": matched_base[0] if matched_base else "",
        "base_type": base_type,
        "source": "database",
        "unusable_reason": message,
        "suggested_movie_name": user_path_name(root) or movie_title,
        "database_path": database_path,
    }


def resolved_movie_result(
    *,
    root: str,
    mapped_root: str,
    note: str,
    matched_base: tuple[str, str] | None,
) -> dict[str, str]:
    result = {
        "movie_dir": mapped_root,
        "base": matched_base[0] if matched_base else user_path_parent(mapped_root),
        "base_type": matched_base[1] if matched_base else "",
        "source": "database",
        "mapping_notice": describe_series_path_resolution(
            note,
            matched_base[1] if matched_base else "",
        ),
    }
    if note:
        result["mapping_note"] = note
        result["database_path"] = normalize_user_path(root)
    root_name = user_path_name(root)
    if root_name:
        result["suggested_movie_name"] = root_name
    return result
