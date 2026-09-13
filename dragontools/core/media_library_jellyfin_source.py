from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .media_library_db import _table_columns, _table_names
from .media_library_utils import _float_or_none, _infer_item_type
from .paths import VIDEO_EXTENSIONS

_IMPORTABLE_JELLYFIN_ITEM_TYPES = {"movie", "series", "season", "episode", "video"}


def _column_map(cursor: sqlite3.Cursor) -> dict[str, str]:
    return {desc[0].casefold(): desc[0] for desc in cursor.description or []}


def _row_value(row: sqlite3.Row, columns: dict[str, str], *names: str, default: Any = None) -> Any:
    for name in names:
        col = columns.get(name.casefold())
        if col is not None:
            return row[col]
    return default


def _pick_jellyfin_item_table(conn: sqlite3.Connection) -> str | None:
    tables = _table_names(conn)
    for candidate in ("TypedBaseItems", "BaseItems", "MediaItems"):
        if candidate in tables:
            columns = _table_columns(conn, candidate)
            if "path" in columns or "name" in columns:
                return candidate
    for table in tables:
        columns = _table_columns(conn, table)
        if "path" in columns and ("name" in columns or "originaltitle" in columns):
            return table
    return None


def _pick_jellyfin_stream_table(conn: sqlite3.Connection) -> str | None:
    tables = _table_names(conn)
    for candidate in ("MediaStreamInfos", "MediaStreams", "mediastreams"):
        if candidate in tables:
            return candidate
    for table in tables:
        columns = _table_columns(conn, table)
        if "streamtype" in columns and "itemid" in columns:
            return table
    return None


def _pick_jellyfin_trickplay_table(conn: sqlite3.Connection) -> str | None:
    tables = _table_names(conn)
    for candidate in ("TrickplayInfos", "TrickplayInfo", "trickplayinfos"):
        if candidate in tables:
            return candidate
    for table in tables:
        columns = _table_columns(conn, table)
        if "itemid" in columns and "thumbnailcount" in columns:
            return table
    return None


def _infer_jellyfin_item_type(type_text: str, path: str) -> str:
    """Mappt Jellyfins expliziten Typ, ohne Movie/Episode aus dem Pfad zu erraten."""
    raw = str(type_text or "").strip()
    qualified = raw.split(",", 1)[0].strip()
    leaf = qualified.rsplit(".", 1)[-1].casefold() if qualified else ""
    explicit = {
        "episode": "episode", "series": "series", "season": "season", "movie": "movie",
        "film": "movie", "video": "video", "musicvideo": "video", "trailer": "video",
        "boxset": "folder", "collectionfolder": "folder", "aggregatefolder": "folder",
        "userrootfolder": "folder", "folder": "folder",
    }
    if leaf in explicit:
        return explicit[leaf]
    if qualified:
        return "video" if Path(path).suffix.casefold() in VIDEO_EXTENSIONS else "folder"
    return _infer_item_type("", path)


def _is_importable_jellyfin_item(item_type: str, path: str) -> bool:
    if item_type not in _IMPORTABLE_JELLYFIN_ITEM_TYPES:
        return False
    if item_type == "video":
        return Path(path).suffix.casefold() in VIDEO_EXTENSIONS
    return True


def _validate_jellyfin_snapshot(conn: sqlite3.Connection) -> None:
    row = conn.execute("PRAGMA quick_check(1)").fetchone()
    result = str(row[0] if row else "").strip()
    if result.casefold() != "ok":
        raise RuntimeError(f"Jellyfin-Datenbank ist nicht konsistent: {result or 'unbekannter SQLite-Konsistenzfehler'}")


def _jellyfin_duration_seconds(row: sqlite3.Row, columns: dict[str, str]) -> float | None:
    ticks_column = columns.get("runtimeticks")
    if ticks_column:
        ticks = _float_or_none(row[ticks_column])
        return ticks / 10_000_000.0 if ticks is not None else None
    return _float_or_none(_row_value(row, columns, "DurationSeconds", default=None))


def _jellyfin_item_id(row: sqlite3.Row, columns: dict[str, str]) -> str:
    return str(
        _row_value(row, columns, "Guid", "Id", "ItemId", "InternalId", "UserDataKey", default="") or ""
    ).casefold()
