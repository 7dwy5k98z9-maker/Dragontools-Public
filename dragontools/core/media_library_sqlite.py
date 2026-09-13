from __future__ import annotations

import sqlite3
from pathlib import Path


def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _sqlite_source_connection(source: Path, *, read_only: bool = False) -> sqlite3.Connection:
    """Öffnet eine SQLite-Quelle optional strikt lesend."""
    if not read_only:
        return sqlite3.connect(str(source))
    source_uri = source.resolve(strict=False).as_uri() + "?mode=ro"
    return sqlite3.connect(source_uri, uri=True)


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {str(row["name"]) for row in rows}


def _table_columns(conn: sqlite3.Connection, table: str) -> dict[str, str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row["name"]).casefold(): str(row["name"]) for row in rows}
