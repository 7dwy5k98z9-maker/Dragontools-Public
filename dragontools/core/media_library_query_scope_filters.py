from __future__ import annotations

from pathlib import Path
from typing import Any

from .media_library_scope import _mapping_prefixes_for_scope, _path_prefix_condition
from .media_library_types import PathMapping


def _append_media_type_filter(where: list[str], media_type_key: str) -> None:
    predicates = {
        "videos": "mi.item_type IN ('episode', 'movie', 'video')",
        "movies": "mi.item_type='movie'",
        "series": "mi.item_type='series'",
        "seasons": "mi.item_type='season'",
        "episodes": "mi.item_type='episode'",
        "folders": "mi.item_type='folder'",
    }
    predicate = predicates.get(media_type_key)
    if predicate:
        where.append(predicate)


def _append_scope_filter(
    db: Path,
    scope_key: str,
    where: list[str],
    params: list[Any],
    *,
    mappings: list[PathMapping] | None = None,
) -> None:
    if scope_key in {"all", ""}:
        return
    if scope_key in {"movies", "filme", "film"}:
        prefixes = _mapping_prefixes_for_scope(db, "movies", mappings=mappings)
        condition = _path_prefix_condition(prefixes, params)
        where.append(f"(mi.item_type='movie'{(' OR ' + condition) if condition else ''})")
        return
    if scope_key in {"anime", "tv"}:
        condition = _path_prefix_condition(
            _mapping_prefixes_for_scope(db, scope_key, mappings=mappings),
            params,
        )
        where.append(condition or "0")
        return
    if scope_key in {"series", "serien"}:
        prefixes = _mapping_prefixes_for_scope(db, "anime", mappings=mappings)
        prefixes += _mapping_prefixes_for_scope(db, "tv", mappings=mappings)
        condition = _path_prefix_condition(prefixes, params)
        where.append(
            f"(mi.item_type IN ('series', 'season', 'episode')"
            f"{(' OR ' + condition) if condition else ''})"
        )
        return
    if scope_key == "other":
        all_prefixes: list[str] = []
        for key in ("movies", "anime", "tv"):
            all_prefixes.extend(_mapping_prefixes_for_scope(db, key, mappings=mappings))
        condition = _path_prefix_condition(all_prefixes, params)
        if condition:
            where.append(f"NOT {condition}")
