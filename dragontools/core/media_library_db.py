from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from .media_library_schema import _create_schema
from .media_library_sqlite import _connect, _sqlite_source_connection, _table_columns, _table_names
from .media_library_types import LibraryStats, SCHEMA_VERSION, _now
from .media_library_utils import _normalize_stream_type

_INITIALIZED_DATABASE_KEYS: set[str] = set()
_INITIALIZED_DATABASE_LOCK = Lock()


def _online_backup_database(
    source: Path,
    destination: Path,
    *,
    source_read_only: bool = False,
) -> None:
    """Erzeugt einen konsistenten SQLite-Snapshot inklusive WAL-Inhalt."""
    with closing(_sqlite_source_connection(source, read_only=source_read_only)) as source_connection:
        with closing(sqlite3.connect(str(destination))) as destination_connection:
            source_connection.backup(destination_connection)


def _snapshot_database(
    source: Path,
    destination: Path,
    *,
    source_read_only: bool = False,
) -> Path:
    """Schreibt einen validen SQLite-Snapshot oder hinterlässt kein Teilziel."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        if source_read_only:
            _online_backup_database(source, destination, source_read_only=True)
        else:
            _online_backup_database(source, destination)
    except (OSError, sqlite3.Error):
        try:
            destination.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return destination


def initialize_database(db_path: str | Path) -> Path:
    db = Path(db_path)
    db.parent.mkdir(parents=True, exist_ok=True)
    with closing(_connect(db)) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        _create_schema(conn)
        conn.commit()
    return db


def initialize_database_once(db_path: str | Path) -> Path:
    """Initialisiert eine bekannte DB pro Prozess nur einmal."""
    db = Path(db_path)
    try:
        key = str(db.resolve(strict=False)).casefold()
    except OSError:
        key = str(db).casefold()
    with _INITIALIZED_DATABASE_LOCK:
        if key in _INITIALIZED_DATABASE_KEYS:
            return db
        initialized = initialize_database(db)
        _INITIALIZED_DATABASE_KEYS.add(key)
        return initialized


def backup_database(db_path: str | Path, reason: str = "backup") -> Path | None:
    db = Path(db_path)
    if not db.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    token = uuid4().hex[:8]
    safe_reason = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in reason).strip("_") or "backup"
    backup = db.with_name(f"{db.stem}_{safe_reason}_{stamp}_{token}{db.suffix}")
    return _snapshot_database(db, backup)


def get_stats(db_path: str | Path) -> LibraryStats:
    db = Path(db_path)
    if not db.exists():
        return LibraryStats(db, SCHEMA_VERSION, 0, 0, 0, 0, 0, 0, 0, "")
    initialize_database_once(db)
    with closing(_connect(db)) as conn:
        schema_version = int(conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()["value"])
        updated_row = conn.execute("SELECT value FROM meta WHERE key='updated_at'").fetchone()
        counts = {
            "media": int(conn.execute("SELECT COUNT(*) AS c FROM media_items").fetchone()["c"]),
            "active": int(conn.execute("SELECT COUNT(*) AS c FROM media_items WHERE active=1 AND exists_flag=1").fetchone()["c"]),
            "inactive": int(conn.execute("SELECT COUNT(*) AS c FROM media_items WHERE active=0 OR exists_flag=0").fetchone()["c"]),
            "movie": int(conn.execute("SELECT COUNT(*) AS c FROM media_items WHERE item_type='movie' AND active=1 AND exists_flag=1").fetchone()["c"]),
            "series": int(conn.execute("SELECT COUNT(*) AS c FROM media_items WHERE item_type='series' AND active=1 AND exists_flag=1").fetchone()["c"]),
            "episode": int(conn.execute("SELECT COUNT(*) AS c FROM media_items WHERE item_type='episode' AND active=1 AND exists_flag=1").fetchone()["c"]),
            "stream": int(conn.execute("SELECT COUNT(*) AS c FROM media_streams").fetchone()["c"]),
        }
    return LibraryStats(
        db, schema_version, counts["media"], counts["active"], counts["inactive"], counts["movie"],
        counts["series"], counts["episode"], counts["stream"], updated_row["value"] if updated_row else "",
    )


def normalize_database_stream_types(db_path: str | Path, *, backup: bool = True) -> int:
    db = initialize_database(db_path)
    updates: list[tuple[str, int]] = []
    with closing(_connect(db)) as conn:
        rows = conn.execute("SELECT id, stream_type, codec, channels, width, height FROM media_streams").fetchall()
        for row in rows:
            normalized = _normalize_stream_type(
                row["stream_type"], codec=row["codec"], channels=row["channels"],
                width=row["width"], height=row["height"],
            )
            if normalized and normalized != str(row["stream_type"] or ""):
                updates.append((normalized, int(row["id"])))
    if not updates:
        return 0
    if backup:
        backup_database(db, "pre_streamtype_normalize")
    with closing(_connect(db)) as conn, conn:
        conn.executemany("UPDATE media_streams SET stream_type=? WHERE id=?", updates)
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('updated_at', ?)", (_now(),))
    return len(updates)


def cleanup_inactive_media_items(db_path: str | Path, *, backup: bool = True) -> int:
    """Entfernt dauerhaft nur inaktive Mediathek-Einträge samt Streamdaten."""
    db = initialize_database(db_path)
    if backup:
        backup_database(db, "pre_cleanup_inactive")
    with closing(_connect(db)) as conn, conn:
        count = int(conn.execute("SELECT COUNT(*) AS c FROM media_items WHERE active=0 OR exists_flag=0").fetchone()["c"])
        conn.execute("DELETE FROM media_items WHERE active=0 OR exists_flag=0")
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('updated_at', ?)", (_now(),))
    return count


def sql_is_read_only(sql: str) -> bool:
    """Nur reine SELECT-Anweisungen gelten konservativ als read-only."""
    statement = (sql or "").lstrip()
    while statement.startswith("--"):
        newline = statement.find("\n")
        if newline < 0:
            return True
        statement = statement[newline + 1 :].lstrip()
    return statement.casefold().startswith("select")


def execute_sql(
    db_path: str | Path,
    sql: str,
    *,
    backup: bool = True,
) -> tuple[list[str], list[tuple[Any, ...]], str]:
    statement = (sql or "").strip()
    if not statement:
        return [], [], "Kein SQL-Befehl eingegeben."
    db = initialize_database(db_path)
    read_only = sql_is_read_only(statement)
    if not read_only and backup:
        backup_database(db, "pre_sql")
    with closing(_connect(db)) as conn, conn:
        if read_only:
            cur = conn.execute(statement)
            columns = [desc[0] for desc in cur.description or []]
            rows = [tuple(row) for row in cur.fetchall()]
            return columns, rows, f"{len(rows)} Zeile(n)."
        conn.executescript(statement)
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('updated_at', ?)", (_now(),))
        return [], [], "SQL-Änderung ausgeführt."


__all__ = [
    "_connect", "_sqlite_source_connection", "_online_backup_database", "_snapshot_database",
    "_table_names", "_table_columns", "_create_schema", "initialize_database", "initialize_database_once",
    "backup_database", "get_stats", "normalize_database_stream_types", "cleanup_inactive_media_items",
    "sql_is_read_only", "execute_sql",
]
