from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable

from .media_library_db import _connect, initialize_database
from .media_library_repository_items import _insert_item, _item_from_media_info, _streams_from_media_info_with_sidecars
from .media_library_types import _now, default_media_library_db_path
from .media_library_utils import _int_or_none, _normalize_title
from .paths import path_compare_key


def _deactivate_paths(conn: sqlite3.Connection, paths: Iterable[str | Path]) -> int:
    unique: list[str] = []
    seen: set[str] = set()
    for path in paths:
        text = str(path or "")
        if not text:
            continue
        key = path_compare_key(text)
        if key in seen:
            continue
        seen.add(key)
        unique.append(text)
    if not unique:
        return 0
    changed = 0
    now = _now()
    for path in unique:
        cur = conn.execute(
            "UPDATE media_items SET exists_flag=0, active=0, updated_at=? WHERE path=?",
            (now, path),
        )
        changed += int(cur.rowcount or 0)
    return changed


def _deactivate_existing_episode_identity(conn: sqlite3.Connection, item: dict[str, Any]) -> int:
    if str(item.get("item_type") or "").casefold() != "episode":
        return 0
    try:
        from .move_conflicts import episode_identity_for_path

        identity = episode_identity_for_path(item.get("path") or item.get("filename") or "")
    except Exception:
        identity = None
    if identity is None:
        season = _int_or_none(item.get("season"))
        episode = _int_or_none(item.get("episode"))
        if season is None or episode is None:
            return 0
        target_episodes = (episode,)
    else:
        season = identity.season
        target_episodes = identity.episodes
    parent_path = str(item.get("parent_path") or "")
    normalized_title = str(item.get("normalized_title") or _normalize_title(item.get("series_title") or item.get("title")))
    rows = conn.execute(
        """
        SELECT id, path, filename, season, episode
        FROM media_items
        WHERE active=1
          AND exists_flag=1
          AND item_type='episode'
          AND season=?
          AND path<>?
          AND (
              lower(coalesce(parent_path, ''))=lower(?)
              OR lower(coalesce(normalized_title, ''))=lower(?)
          )
        """,
        (season, str(item.get("path") or ""), parent_path, normalized_title),
    ).fetchall()
    ids: list[int] = []
    for row in rows:
        row_identity = None
        try:
            row_identity = episode_identity_for_path(row["path"] or row["filename"] or "")
        except Exception:
            row_identity = None
        if row_identity is not None:
            if row_identity.season != season or row_identity.episodes != target_episodes:
                continue
        elif (_int_or_none(row["episode"]),) != target_episodes:
            continue
        ids.append(int(row["id"]))
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    cur = conn.execute(
        f"UPDATE media_items SET exists_flag=0, active=0, updated_at=? WHERE id IN ({placeholders})",
        (_now(), *ids),
    )
    return int(cur.rowcount or 0)


def record_moved_file(
    db_path: str | Path,
    source_path: str | Path,
    dest_path: str | Path,
    tools: Any = None,
    replaced_paths: Iterable[str | Path] = (),
) -> None:
    from .media_analyzer import analyze_media

    db = initialize_database(db_path)
    dest = Path(dest_path)
    if not dest.exists():
        raise FileNotFoundError(f"Zieldatei nicht gefunden: {dest}")
    info = analyze_media(str(dest), tools=tools)
    item = _item_from_media_info(dest, info)
    streams = _streams_from_media_info_with_sidecars(dest, info)
    with closing(_connect(db)) as conn:
        with conn:
            _deactivate_paths(conn, [source_path, *list(replaced_paths or [])])
            _deactivate_existing_episode_identity(conn, item)
            _insert_item(conn, item, streams)
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('updated_at', ?)", (_now(),))


def record_moved_file_from_settings(
    settings: Any,
    source_path: str | Path,
    dest_path: str | Path,
    tools: Any = None,
    replaced_paths: Iterable[str | Path] = (),
) -> bool:
    from .settings import (
        SET_KEY_MEDIA_LIBRARY_DB_PATH,
        SET_KEY_MEDIA_LIBRARY_ENABLED,
    )

    enabled = settings.value(SET_KEY_MEDIA_LIBRARY_ENABLED, False, type=bool)
    if not enabled:
        return False
    db_path = settings.value(SET_KEY_MEDIA_LIBRARY_DB_PATH, str(default_media_library_db_path()), type=str)
    if not db_path:
        return False
    record_moved_file(db_path, source_path, dest_path, tools=tools, replaced_paths=replaced_paths)
    return True
