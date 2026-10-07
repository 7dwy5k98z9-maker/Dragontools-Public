from __future__ import annotations

from collections import defaultdict
from contextlib import closing
from pathlib import Path
from typing import Any

from .media_library_classification import _find_deviations
from .media_library_db import _connect, initialize_database_once
from .media_library_paths import get_path_mappings
from .media_library_query import (
    _append_media_type_filter, _append_preset_filter, _append_scope_filter,
    _append_text_filter, _build_search_query, _build_search_sql_fragments,
)
from .media_library_scope import _area_for_path
from .media_library_search_enrichment import enrich_search_rows_with_streams
from .media_library_utils import _int_or_none
from .move_conflicts import episode_identity_for_path
from .path_syntax import path_compare_key

def _search_duplicate_active_episode_rows(
    db_path: str | Path,
    text: str,
    *,
    limit: int | None,
    scope: str,
    media_type: str,
) -> list[dict[str, Any]]:
    """Find duplicate episode identities without enriching the whole library.

    The old implementation recursively called ``search_library(..., limit=None)``
    and therefore loaded/enriched every active episode (including all stream
    metadata) before it knew which rows were duplicates.  On ~100k-item
    libraries this made a narrow diagnostics preset one of the most expensive
    searches in the UI.  Keep the discovery pass deliberately lightweight and
    enrich only the final duplicate rows.
    """
    if media_type not in {"all", "videos", "episodes", ""}:
        return []

    db = Path(db_path)
    if not db.exists():
        return []
    initialize_database_once(db)

    where = ["mi.exists_flag=1", "mi.active=1", "mi.item_type='episode'"]
    params: list[Any] = []
    with closing(_connect(db)) as conn:
        mappings = get_path_mappings(db, connection=conn)
        _append_scope_filter(db, (scope or "all").casefold(), where, params, mappings=mappings)
        _append_text_filter(where, params, text)
        candidates = conn.execute(
            f"""
            SELECT mi.id AS _media_id, mi.path, mi.filename, mi.parent_path,
                   mi.series_title, mi.title, mi.season, mi.episode
              FROM media_items mi
             WHERE {' AND '.join(where)}
            """,
            params,
        ).fetchall()

        groups: dict[tuple[str, int, tuple[int, ...]], list[dict[str, Any]]] = defaultdict(list)
        for raw in candidates:
            row = dict(raw)
            identity = episode_identity_for_path(row.get("path") or row.get("filename") or "")
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
            row["deviation_reason"] = f"Doppelte aktive SxxExx im Zielordner: {label}"
            groups[key].append(row)

        duplicates = [row for group in groups.values() if len(group) > 1 for row in group]
        duplicates.sort(
            key=lambda row: (
                str(row.get("series_title") or row.get("title") or row.get("filename") or "").casefold(),
                int(row.get("season") or 0),
                int(row.get("episode") or 0),
                str(row.get("filename") or "").casefold(),
            )
        )
        if limit is not None:
            duplicates = duplicates[: max(1, int(limit))]
        if not duplicates:
            return []

        reason_by_id = {int(row["_media_id"]): str(row["deviation_reason"]) for row in duplicates}
        wanted_ids = list(reason_by_id)
        result_rows: list[dict[str, Any]] = []
        search_sql = _build_search_sql_fragments()
        for offset in range(0, len(wanted_ids), 400):
            chunk = wanted_ids[offset : offset + 400]
            placeholders = ",".join("?" for _ in chunk)
            query = _build_search_query(
                [f"mi.id IN ({placeholders})"],
                deviation_criterion="",
                sql=search_sql,
                apply_limit=False,
            )
            result_rows.extend(dict(row) for row in conn.execute(query, chunk).fetchall())

        for row in result_rows:
            media_id = int(row.get("_media_id") or 0)
            row["deviation_reason"] = reason_by_id.get(media_id, "")
        enrich_search_rows_with_streams(conn, result_rows)

    for row in result_rows:
        row["area"] = _area_for_path(row.get("path"), mappings)
    result_rows.sort(
        key=lambda row: (
            str(row.get("series_title") or row.get("title") or row.get("filename") or "").casefold(),
            int(row.get("season") or 0),
            int(row.get("episode") or 0),
            str(row.get("filename") or "").casefold(),
        )
    )
    return result_rows


def search_library(
    db_path: str | Path,
    preset: str = "all",
    text: str = "",
    limit: int | None = 500,
    *,
    scope: str = "all",
    media_type: str = "all",
) -> list[dict[str, Any]]:
    db = Path(db_path)
    if not db.exists():
        return []
    initialize_database_once(db)

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
    with closing(_connect(db)) as conn:
        # Scope mapping and the actual SELECT share one read connection.
        mappings = get_path_mappings(db, connection=conn)
        _append_scope_filter(db, scope_key, where, params, mappings=mappings)
        sql = _build_search_sql_fragments()
        _append_preset_filter(preset_key, deviation_criterion, where, params, sql)
        _append_text_filter(where, params, text)

        query = _build_search_query(
            where,
            deviation_criterion=deviation_criterion,
            sql=sql,
            apply_limit=limit is not None,
        )
        if not deviation_criterion and limit is not None:
            params.append(max(1, int(limit)))
        rows = [dict(row) for row in conn.execute(query, params).fetchall()]
        enrich_search_rows_with_streams(conn, rows)

    for row in rows:
        row.setdefault("deviation_reason", "")
        row["area"] = _area_for_path(row.get("path"), mappings)
    if deviation_criterion:
        deviation_limit = max(1, len(rows)) if limit is None else max(1, int(limit))
        return _find_deviations(rows, deviation_criterion, deviation_limit)
    return rows
