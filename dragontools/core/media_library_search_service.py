from __future__ import annotations

from collections import defaultdict
from contextlib import closing
from pathlib import Path
from typing import Any

from .media_library_classification import _find_deviations
from .media_library_db import _connect, initialize_database
from .media_library_paths import get_path_mappings
from .media_library_query import (
    _append_media_type_filter, _append_preset_filter, _append_scope_filter,
    _append_text_filter, _build_search_query, _build_search_sql_fragments,
)
from .media_library_scope import _area_for_path
from .media_library_utils import _int_or_none
from .paths import path_compare_key

def _search_duplicate_active_episode_rows(
    db_path: str | Path,
    text: str,
    *,
    limit: int,
    scope: str,
    media_type: str,
) -> list[dict[str, Any]]:
    if media_type not in {"all", "videos", "episodes", ""}:
        return []
    rows = search_library(
        db_path,
        "all",
        text,
        limit=1_000_000,
        scope=scope,
        media_type="episodes",
    )
    try:
        from .move_conflicts import episode_identity_for_path
    except Exception:
        episode_identity_for_path = None

    groups: dict[tuple[str, int, tuple[int, ...]], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        identity = episode_identity_for_path(row.get("path") or row.get("filename") or "") if episode_identity_for_path else None
        if identity is not None:
            season = identity.season
            episodes = identity.episodes
            label = identity.label
        else:
            season = _int_or_none(row.get("season"))
            episode = _int_or_none(row.get("episode"))
            if season is None or episode is None:
                continue
            episodes = (episode,)
            label = f"S{season:02d}E{episode:02d}"
        parent_key = path_compare_key(row.get("parent_path") or "")
        key = (parent_key, int(season), tuple(int(ep) for ep in episodes))
        duplicate_row = dict(row)
        duplicate_row["deviation_reason"] = f"Doppelte aktive SxxExx im Zielordner: {label}"
        groups[key].append(duplicate_row)

    duplicates: list[dict[str, Any]] = []
    for group in groups.values():
        if len(group) > 1:
            duplicates.extend(group)
    duplicates.sort(
        key=lambda row: (
            str(row.get("series_title") or row.get("title") or row.get("filename") or "").casefold(),
            int(row.get("season") or 0),
            int(row.get("episode") or 0),
            str(row.get("filename") or "").casefold(),
        )
    )
    return duplicates[: max(1, int(limit))]


def search_library(
    db_path: str | Path,
    preset: str = "all",
    text: str = "",
    limit: int = 500,
    *,
    scope: str = "all",
    media_type: str = "all",
) -> list[dict[str, Any]]:
    db = Path(db_path)
    if not db.exists():
        return []
    initialize_database(db)

    preset_key = (preset or "all").casefold()
    scope_key = (scope or "all").casefold()
    media_type_key = (media_type or "all").casefold()
    if preset_key == "duplicate_active_sxxexx":
        return _search_duplicate_active_episode_rows(
            db,
            text,
            limit=limit,
            scope=scope_key,
            media_type=media_type_key,
        )

    deviation_criterion = preset_key.removeprefix("deviation_") if preset_key.startswith("deviation_") else ""
    where = ["mi.exists_flag=1", "mi.active=1"]
    params: list[Any] = []
    if preset_key != "all":
        where.append("mi.item_type IN ('episode', 'movie', 'video')")

    _append_media_type_filter(where, media_type_key)
    _append_scope_filter(db, scope_key, where, params)
    sql = _build_search_sql_fragments()
    _append_preset_filter(preset_key, deviation_criterion, where, params, sql)
    _append_text_filter(where, params, text)

    query = _build_search_query(where, deviation_criterion=deviation_criterion, sql=sql)
    if not deviation_criterion:
        params.append(max(1, int(limit)))

    with closing(_connect(db)) as conn:
        rows = [dict(row) for row in conn.execute(query, params).fetchall()]

    mappings = get_path_mappings(db)
    for row in rows:
        row.setdefault("deviation_reason", "")
        row["area"] = _area_for_path(row.get("path"), mappings)
    if deviation_criterion:
        return _find_deviations(rows, deviation_criterion, max(1, int(limit)))
    return rows
