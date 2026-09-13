from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Iterable

from .media_library_db import _connect, initialize_database_once
from .german_title_variants import german_umlaut_search_variants
from .media_library_series_paths import _match_base, _series_root_candidates_for_current_paths, _year_suffix_from_text
from .media_library_types import PathMapping, default_media_library_db_path, describe_series_path_resolution
from .media_library_utils import _normalize_title
from .paths import normalize_user_path, path_compare_key, user_path_name, user_path_parent
from .media_library_path_mappings import (
    _area_from_root,
    _area_label,
    _mapping_candidates_from_search_bases,
    _unique_mappings,
    get_path_mappings,
    load_path_mappings,
)


def _movie_lookup_rows(
    conn: sqlite3.Connection,
    *,
    target_norms: tuple[str, ...],
    movie_title: str,
) -> list[sqlite3.Row]:
    plain_names = tuple(
        dict.fromkeys(
            variant.strip().casefold()
            for variant in german_umlaut_search_variants(movie_title)
            if variant.strip()
        )
    )
    if not target_norms and not plain_names:
        return []
    norm_placeholders = ",".join("?" for _ in target_norms) or "NULL"
    plain_placeholders = ",".join("?" for _ in plain_names) or "NULL"

    return conn.execute(
        f"""
        SELECT item_type, title, original_title, path, parent_path, filename, year
        FROM media_items
        WHERE exists_flag=1
          AND active=1
          AND item_type IN ('movie', 'video')
          AND (
              normalized_title IN ({norm_placeholders})
              OR lower(trim(coalesce(title, ''))) IN ({plain_placeholders})
              OR lower(trim(coalesce(original_title, ''))) IN ({plain_placeholders})
              OR lower(trim(coalesce(filename, ''))) IN ({plain_placeholders})
          )
        ORDER BY
            CASE item_type WHEN 'movie' THEN 0 ELSE 1 END,
            CASE WHEN year IS NULL THEN 1 ELSE 0 END,
            year,
            coalesce(title, original_title, filename, path)
        LIMIT 1000
        """,
        (*target_norms, *plain_names, *plain_names, *plain_names),
    ).fetchall()


def _movie_dir_from_db_row(row: sqlite3.Row) -> str:
    parent = str(row["parent_path"] or "").strip()
    if parent:
        return parent
    path = str(row["path"] or "").strip()
    return user_path_parent(path) if path else ""


def find_movie_root(
    db_path: str | Path,
    movie_title: str,
    search_bases: Iterable[tuple[str, str]] | Iterable[str] = (),
    *,
    mappings: Iterable[PathMapping] = (),
    stored_mappings: Iterable[PathMapping] = (),
    require_existing: bool = False,
    include_unusable: bool = False,
    year: int | None = None,
    dir_exists: Callable[[str], bool] | None = None,
) -> dict[str, str] | None:
    db = Path(db_path)
    if not db.exists() or not movie_title:
        return None
    initialize_database_once(db)
    target_norms = tuple(
        dict.fromkeys(
            _normalize_title(variant)
            for variant in german_umlaut_search_variants(movie_title)
            if _normalize_title(variant)
        )
    )
    if not target_norms:
        return None
    target_year = _year_suffix_from_text(movie_title) or (int(year) if year else None)

    bases: list[tuple[str, str]] = []
    for entry in search_bases or []:
        if isinstance(entry, tuple):
            bases.append((str(entry[0]), str(entry[1] or "")))
        else:
            bases.append((str(entry), ""))

    with closing(_connect(db)) as conn:
        rows = _movie_lookup_rows(conn, target_norms=target_norms, movie_title=movie_title)

    search_base_mappings = _mapping_candidates_from_search_bases(bases)
    current_mappings = _unique_mappings([*(mappings or []), *search_base_mappings])
    stored_mappings_list = _unique_mappings(stored_mappings or [])
    rejected: dict[str, str] = {}

    def remember_rejected(root: str, mapped_root: str, reason: str, matched_base: tuple[str, str] | None) -> None:
        nonlocal rejected
        if rejected and not matched_base:
            return
        area = _area_from_root(root, [*stored_mappings_list, *current_mappings])
        base_type = matched_base[1] if matched_base else _area_label(area)
        prefix = "Mediathek-Filmtreffer ist aktuell nicht erreichbar"
        if base_type:
            prefix += f" (Bereich {base_type})"
        message = f"{prefix}: {mapped_root}"
        db_path_text = normalize_user_path(root)
        if db_path_text and path_compare_key(db_path_text) != path_compare_key(mapped_root):
            message += f" | DB-Pfad: {db_path_text}"
        if reason:
            message += f" | Grund: {reason}"
        rejected = {
            "movie_dir": "",
            "base": matched_base[0] if matched_base else "",
            "base_type": base_type,
            "source": "database",
            "unusable_reason": message,
            "suggested_movie_name": user_path_name(root) or movie_title,
            "database_path": db_path_text,
        }

    for row in rows:
        root = _movie_dir_from_db_row(row)
        if not root:
            continue
        names = (
            str(row["title"] or ""),
            str(row["original_title"] or ""),
            str(row["filename"] or ""),
            user_path_name(root),
        )
        if not set(target_norms).intersection({_normalize_title(name) for name in names if name}):
            continue
        row_year = row["year"] if "year" in row.keys() else None
        try:
            row_year = int(row_year) if row_year else None
        except (TypeError, ValueError):
            row_year = None
        candidate_year = _year_suffix_from_text(user_path_name(root)) or row_year
        if target_year and candidate_year and candidate_year != target_year:
            continue
        for mapped_root, note in _series_root_candidates_for_current_paths(
            root,
            current_mappings=current_mappings,
            stored_mappings=stored_mappings_list,
            search_bases=bases,
        ):
            matched_base = _match_base(mapped_root, bases)
            if bases and not matched_base:
                remember_rejected(
                    root,
                    mapped_root,
                    "liegt nicht unter den aktuell eingestellten Speicherpfaden",
                    matched_base,
                )
                continue
            if require_existing:
                exists = dir_exists(mapped_root) if dir_exists else Path(mapped_root).is_dir()
                if not exists:
                    remember_rejected(root, mapped_root, "Ordner existiert nicht oder ist nicht erreichbar", matched_base)
                    continue
            result = {
                "movie_dir": mapped_root,
                "base": matched_base[0] if matched_base else user_path_parent(mapped_root),
                "base_type": matched_base[1] if matched_base else "",
                "source": "database",
            }
            result["mapping_notice"] = describe_series_path_resolution(note, result["base_type"])
            if note:
                result["mapping_note"] = note
                result["database_path"] = normalize_user_path(root)
            root_name = user_path_name(root)
            if root_name:
                result["suggested_movie_name"] = root_name
            return result
    if include_unusable and rejected:
        return rejected
    return None


def find_movie_dir_from_settings(
    settings: Any,
    movie_title: str,
    search_bases: Iterable[tuple[str, str]],
    *,
    year: int | None = None,
    dir_exists: Callable[[str], bool] | None = None,
) -> dict[str, str] | None:
    from .settings import (
        SET_KEY_MEDIA_LIBRARY_DB_PATH,
        SET_KEY_MEDIA_LIBRARY_ENABLED,
        SET_KEY_MEDIA_LIBRARY_PATH_MAPPINGS,
        SET_KEY_MEDIA_LIBRARY_PREFLIGHT_ENABLED,
    )

    if not settings.value(SET_KEY_MEDIA_LIBRARY_ENABLED, False, type=bool):
        return None
    if not settings.value(SET_KEY_MEDIA_LIBRARY_PREFLIGHT_ENABLED, True, type=bool):
        return None
    db_path = settings.value(SET_KEY_MEDIA_LIBRARY_DB_PATH, str(default_media_library_db_path()), type=str)
    if not db_path:
        return None
    configured_mappings = load_path_mappings(settings.value(SET_KEY_MEDIA_LIBRARY_PATH_MAPPINGS, "", type=str))
    try:
        stored_mappings = get_path_mappings(db_path)
    except Exception:
        stored_mappings = []
    mappings = configured_mappings or stored_mappings
    if not mappings:
        try:
            mappings = get_path_mappings(db_path)
        except Exception:
            mappings = []
    return find_movie_root(
        db_path,
        movie_title,
        search_bases,
        mappings=mappings,
        stored_mappings=stored_mappings,
        require_existing=True,
        include_unusable=True,
        year=year,
        dir_exists=dir_exists,
    )
