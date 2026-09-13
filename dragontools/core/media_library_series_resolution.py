from __future__ import annotations

import re
import sqlite3
from typing import Iterable

from .media_library_path_mappings import _area_from_root, _area_label
from .media_library_types import PathMapping, describe_series_path_resolution
from .media_library_utils import _normalize_title
from .path_syntax import normalize_user_path, path_compare_key, user_path_name, user_path_parent


def _year_suffix_from_text(value: str | None) -> int | None:
    match = re.search(r"\((19\d{2}|20\d{2})\)\s*$", str(value or "").strip())
    return int(match.group(1)) if match else None


def _series_root_from_db_row(row: sqlite3.Row) -> str:
    path = str(row["path"] or row["parent_path"] or "")
    item_type = str(row["item_type"] or "").casefold()
    if item_type == "series":
        return path
    if item_type == "season":
        return user_path_parent(path)
    if item_type == "episode":
        parent = user_path_parent(path)
        if user_path_name(parent).casefold().startswith(("staffel", "season", "saison", "special")):
            return user_path_parent(parent)
        return parent
    return path


def _normalized_search_bases(search_bases: Iterable[tuple[str, str]] | Iterable[str]) -> list[tuple[str, str]]:
    bases: list[tuple[str, str]] = []
    for entry in search_bases or []:
        if isinstance(entry, tuple):
            bases.append((str(entry[0]), str(entry[1] or "")))
        else:
            bases.append((str(entry), ""))
    return bases


def _series_candidate_year(row: sqlite3.Row, root: str) -> int | None:
    candidate_year = _year_suffix_from_text(user_path_name(root))
    if candidate_year is not None:
        return candidate_year
    if str(row["item_type"] or "").casefold() not in {"series", "folder"}:
        return None
    try:
        return int(row["year"]) if row["year"] else None
    except (TypeError, ValueError):
        return None


def _ambiguous_series_years(rows: Iterable[sqlite3.Row], target_norm: str) -> set[int]:
    years: set[int] = set()
    for row in rows:
        name = str(row["series_title"] or row["title"] or "")
        if _normalize_title(name) != target_norm:
            continue
        root = _series_root_from_db_row(row)
        if not root:
            continue
        candidate_year = _series_candidate_year(row, root)
        if candidate_year:
            years.add(candidate_year)
    return years


def _unusable_series_result(
    *,
    root: str,
    mapped_root: str,
    reason: str,
    matched_base: tuple[str, str] | None,
    series_name: str,
    stored_mappings: list[PathMapping],
    current_mappings: list[PathMapping],
) -> dict[str, str]:
    area = _area_from_root(root, [*stored_mappings, *current_mappings])
    base_type = matched_base[1] if matched_base else _area_label(area)
    prefix = "Mediathek-Treffer ist aktuell nicht erreichbar"
    if base_type:
        prefix += f" (Bereich {base_type})"
    message = f"{prefix}: {mapped_root}"
    database_path = normalize_user_path(root)
    if database_path and path_compare_key(database_path) != path_compare_key(mapped_root):
        message += f" | DB-Pfad: {database_path}"
    if reason:
        message += f" | Grund: {reason}"
    return {
        "series_dir": "",
        "base": matched_base[0] if matched_base else "",
        "base_type": base_type,
        "source": "database",
        "unusable_reason": message,
        "suggested_series_name": user_path_name(root) or series_name,
        "database_path": database_path,
    }


def _resolved_series_result(
    *,
    root: str,
    mapped_root: str,
    note: str,
    matched_base: tuple[str, str] | None,
    series_name: str,
) -> dict[str, str]:
    result = {
        "series_dir": mapped_root,
        "base": matched_base[0] if matched_base else user_path_parent(mapped_root),
        "base_type": matched_base[1] if matched_base else "",
        "source": "database",
    }
    result["mapping_notice"] = describe_series_path_resolution(note, result["base_type"])
    if note:
        result["mapping_note"] = note
        result["database_path"] = normalize_user_path(root)
    root_name = user_path_name(root)
    if root_name and _normalize_title(root_name) != _normalize_title(series_name):
        result["suggested_series_name"] = root_name
    return result
