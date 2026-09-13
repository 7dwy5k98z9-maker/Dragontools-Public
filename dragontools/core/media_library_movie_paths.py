from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Iterable

from .media_library_db import _connect, initialize_database_once
from .german_title_variants import german_umlaut_search_variants
from .media_library_series_paths import _match_base, _series_root_candidates_for_current_paths
from .media_library_types import PathMapping, default_media_library_db_path
from .media_library_utils import _normalize_title
from .media_library_movie_resolution import (
    movie_candidate_year,
    movie_row_matches,
    resolved_movie_result,
    unusable_movie_result,
)
from .media_library_series_resolution import _normalized_search_bases, _year_suffix_from_text
from .path_syntax import user_path_parent
from .media_library_path_mappings import (
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
    bases = _normalized_search_bases(search_bases)

    with closing(_connect(db)) as conn:
        rows = _movie_lookup_rows(conn, target_norms=target_norms, movie_title=movie_title)

    current_mappings = _unique_mappings([
        *(mappings or []),
        *_mapping_candidates_from_search_bases(bases),
    ])
    stored_mappings_list = _unique_mappings(stored_mappings or [])
    rejected: dict[str, str] = {}

    for row in rows:
        root = _movie_dir_from_db_row(row)
        if not root or not movie_row_matches(row, root, target_norms):
            continue
        candidate_year = movie_candidate_year(row, root)
        if target_year and candidate_year and candidate_year != target_year:
            continue
        for mapped_root, note in _series_root_candidates_for_current_paths(
            root,
            current_mappings=current_mappings,
            stored_mappings=stored_mappings_list,
            search_bases=bases,
        ):
            matched_base = _match_base(mapped_root, bases)
            rejection_reason = ""
            if bases and not matched_base:
                rejection_reason = "liegt nicht unter den aktuell eingestellten Speicherpfaden"
            elif require_existing:
                exists = dir_exists(mapped_root) if dir_exists else Path(mapped_root).is_dir()
                if not exists:
                    rejection_reason = "Ordner existiert nicht oder ist nicht erreichbar"
            if rejection_reason:
                if matched_base or not rejected:
                    rejected = unusable_movie_result(
                        root=root,
                        mapped_root=mapped_root,
                        reason=rejection_reason,
                        matched_base=matched_base,
                        movie_title=movie_title,
                        stored_mappings=stored_mappings_list,
                        current_mappings=current_mappings,
                    )
                continue
            return resolved_movie_result(
                root=root,
                mapped_root=mapped_root,
                note=note,
                matched_base=matched_base,
            )

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
    from .settings_media_library import SET_KEY_MEDIA_LIBRARY_DB_PATH, SET_KEY_MEDIA_LIBRARY_ENABLED, SET_KEY_MEDIA_LIBRARY_PATH_MAPPINGS, SET_KEY_MEDIA_LIBRARY_PREFLIGHT_ENABLED

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
