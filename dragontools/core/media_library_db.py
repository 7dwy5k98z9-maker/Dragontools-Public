from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .media_library_types import LibraryStats, SCHEMA_VERSION, _now
from .media_library_utils import _normalize_stream_type

def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _sqlite_source_connection(source: Path, *, read_only: bool = False) -> sqlite3.Connection:
    """Oeffnet eine SQLite-Quelle optional strikt lesend.

    Der Read-only-Modus wird insbesondere fuer aktive Fremddatenbanken wie
    Jellyfin verwendet. So kann die Online Backup API DB + WAL konsistent lesen,
    ohne die Quelldatenbank selbst zu beschreiben.
    """
    if not read_only:
        return sqlite3.connect(str(source))
    source_uri = source.resolve(strict=False).as_uri() + "?mode=ro"
    return sqlite3.connect(source_uri, uri=True)


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
    """Schreibt einen validen SQLite-Snapshot oder hinterlaesst kein Teilziel."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        if source_read_only:
            _online_backup_database(source, destination, source_read_only=True)
        else:
            _online_backup_database(source, destination)
    except (OSError, sqlite3.Error):
        # Ein partiell erzeugtes Ziel darf niemals wie ein gueltiger Export
        # oder ein Sicherheitsbackup aussehen.
        try:
            destination.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return destination


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {str(row["name"]) for row in rows}


def _table_columns(conn: sqlite3.Connection, table: str) -> dict[str, str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row["name"]).casefold(): str(row["name"]) for row in rows}


def initialize_database(db_path: str | Path) -> Path:
    db = Path(db_path)
    db.parent.mkdir(parents=True, exist_ok=True)
    with closing(_connect(db)) as conn:
        _create_schema(conn)
        conn.commit()
    return db


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS path_mappings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT NOT NULL DEFAULT '',
            external_prefix TEXT NOT NULL,
            local_prefix TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS media_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_type TEXT NOT NULL DEFAULT 'video',
            title TEXT,
            series_title TEXT,
            season INTEGER,
            episode INTEGER,
            year INTEGER,
            source TEXT,
            source_id TEXT,
            provider TEXT,
            path TEXT NOT NULL UNIQUE,
            parent_path TEXT,
            filename TEXT,
            normalized_title TEXT,
            container TEXT,
            duration_s REAL,
            size_bytes INTEGER,
            width INTEGER,
            height INTEGER,
            video_codec TEXT,
            video_bitrate INTEGER,
            overall_bitrate INTEGER,
            is_hdr INTEGER NOT NULL DEFAULT 0,
            has_hdr10plus INTEGER NOT NULL DEFAULT 0,
            has_dolby_vision INTEGER NOT NULL DEFAULT 0,
            dv_profile TEXT,
            nfo_status TEXT NOT NULL DEFAULT 'unknown',
            trickplay_status TEXT NOT NULL DEFAULT 'unknown',
            analysis_status TEXT NOT NULL DEFAULT 'unknown',
            exists_flag INTEGER NOT NULL DEFAULT 1,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_media_items_title ON media_items(normalized_title);
        CREATE INDEX IF NOT EXISTS idx_media_items_series ON media_items(series_title);
        CREATE INDEX IF NOT EXISTS idx_media_items_type ON media_items(item_type);
        CREATE INDEX IF NOT EXISTS idx_media_items_path ON media_items(path);
        CREATE INDEX IF NOT EXISTS idx_media_items_parent ON media_items(parent_path);
        CREATE INDEX IF NOT EXISTS idx_media_items_video ON media_items(video_codec, width, height);
        CREATE INDEX IF NOT EXISTS idx_media_items_active_episode ON media_items(active, item_type, parent_path, season, episode);

        CREATE TABLE IF NOT EXISTS media_streams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            media_id INTEGER NOT NULL REFERENCES media_items(id) ON DELETE CASCADE,
            stream_type TEXT NOT NULL,
            stream_index INTEGER,
            codec TEXT,
            language TEXT,
            forced INTEGER NOT NULL DEFAULT 0,
            channels INTEGER,
            channel_layout TEXT,
            bitrate INTEGER,
            width INTEGER,
            height INTEGER,
            hdr_format TEXT,
            dv_profile TEXT,
            pix_fmt TEXT,
            bit_depth INTEGER,
            profile TEXT,
            duration_s REAL,
            frame_count INTEGER,
            frame_rate TEXT,
            frame_rate_mode TEXT,
            color_space TEXT,
            color_transfer TEXT,
            color_primaries TEXT,
            title TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_media_streams_media ON media_streams(media_id);
        CREATE INDEX IF NOT EXISTS idx_media_streams_media_type ON media_streams(media_id, stream_type);
        CREATE INDEX IF NOT EXISTS idx_media_streams_type_lang ON media_streams(stream_type, language);
        CREATE INDEX IF NOT EXISTS idx_media_streams_type_codec ON media_streams(stream_type, codec);
        """
    )
    _ensure_media_items_schema(conn)
    _ensure_media_streams_schema(conn)
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('updated_at', ?)", (_now(),))


def _ensure_media_items_schema(conn: sqlite3.Connection) -> None:
    columns = _table_columns(conn, "media_items") if "media_items" in _table_names(conn) else {}
    if "active" not in columns:
        conn.execute("ALTER TABLE media_items ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
    if "size_bytes" not in columns:
        conn.execute("ALTER TABLE media_items ADD COLUMN size_bytes INTEGER")
    conn.execute("UPDATE media_items SET active=0 WHERE exists_flag=0")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_media_items_active_episode "
        "ON media_items(active, item_type, parent_path, season, episode)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_media_items_size ON media_items(size_bytes)")


def _ensure_media_streams_schema(conn: sqlite3.Connection) -> None:
    columns = _table_columns(conn, "media_streams") if "media_streams" in _table_names(conn) else {}
    additions = {
        "profile": "TEXT",
        "duration_s": "REAL",
        "frame_count": "INTEGER",
        "frame_rate": "TEXT",
        "frame_rate_mode": "TEXT",
        "color_space": "TEXT",
        "color_transfer": "TEXT",
        "color_primaries": "TEXT",
    }
    for name, sql_type in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE media_streams ADD COLUMN {name} {sql_type}")


def backup_database(db_path: str | Path, reason: str = "backup") -> Path | None:
    db = Path(db_path)
    if not db.exists():
        return None
    # Mikrosekunden + kurzer UUID-Anteil verhindern Kollisionen auch dann,
    # wenn mehrere Sicherungen unmittelbar nacheinander oder parallel entstehen.
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    token = uuid4().hex[:8]
    safe_reason = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in reason).strip("_") or "backup"
    backup = db.with_name(f"{db.stem}_{safe_reason}_{stamp}_{token}{db.suffix}")
    # SQLite-Datenbanken im WAL-Modus duerfen nicht per Dateikopie gesichert
    # werden: commitete Seiten koennen noch ausschliesslich im WAL liegen.
    # Die Online Backup API erzeugt dagegen einen konsistenten Snapshot aus
    # Datenbank + WAL, ohne die Quelldatenbank zu veraendern.
    return _snapshot_database(db, backup)


def get_stats(db_path: str | Path) -> LibraryStats:
    db = Path(db_path)
    if not db.exists():
        return LibraryStats(db, SCHEMA_VERSION, 0, 0, 0, 0, 0, 0, 0, "")
    with closing(_connect(db)) as conn:
        _create_schema(conn)
        schema_version = int(
            conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()["value"]
        )
        updated_row = conn.execute("SELECT value FROM meta WHERE key='updated_at'").fetchone()
        media_count = int(conn.execute("SELECT COUNT(*) AS c FROM media_items").fetchone()["c"])
        active_count = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM media_items WHERE active=1 AND exists_flag=1"
            ).fetchone()["c"]
        )
        inactive_count = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM media_items WHERE active=0 OR exists_flag=0"
            ).fetchone()["c"]
        )
        movie_count = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM media_items WHERE item_type='movie' AND active=1 AND exists_flag=1"
            ).fetchone()["c"]
        )
        series_count = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM media_items WHERE item_type='series' AND active=1 AND exists_flag=1"
            ).fetchone()["c"]
        )
        episode_count = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM media_items WHERE item_type='episode' AND active=1 AND exists_flag=1"
            ).fetchone()["c"]
        )
        stream_count = int(conn.execute("SELECT COUNT(*) AS c FROM media_streams").fetchone()["c"])
    return LibraryStats(
        db,
        schema_version,
        media_count,
        active_count,
        inactive_count,
        movie_count,
        series_count,
        episode_count,
        stream_count,
        updated_row["value"] if updated_row else "",
    )


def normalize_database_stream_types(db_path: str | Path, *, backup: bool = True) -> int:
    db = initialize_database(db_path)
    updates: list[tuple[str, int]] = []
    with closing(_connect(db)) as conn:
        rows = conn.execute(
            """
            SELECT id, stream_type, codec, channels, width, height
            FROM media_streams
            """
        ).fetchall()
        for row in rows:
            normalized = _normalize_stream_type(
                row["stream_type"],
                codec=row["codec"],
                channels=row["channels"],
                width=row["width"],
                height=row["height"],
            )
            if normalized and normalized != str(row["stream_type"] or ""):
                updates.append((normalized, int(row["id"])))

    if not updates:
        return 0
    if backup:
        backup_database(db, "pre_streamtype_normalize")
    with closing(_connect(db)) as conn:
        with conn:
            conn.executemany("UPDATE media_streams SET stream_type=? WHERE id=?", updates)
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('updated_at', ?)", (_now(),))
    return len(updates)


def cleanup_inactive_media_items(db_path: str | Path, *, backup: bool = True) -> int:
    """Entfernt dauerhaft nur inaktive Mediathek-Einträge samt Streamdaten."""
    db = initialize_database(db_path)
    if backup:
        backup_database(db, "pre_cleanup_inactive")
    with closing(_connect(db)) as conn:
        with conn:
            _create_schema(conn)
            count = int(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM media_items WHERE active=0 OR exists_flag=0"
                ).fetchone()["c"]
            )
            conn.execute("DELETE FROM media_items WHERE active=0 OR exists_flag=0")
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('updated_at', ?)", (_now(),))
    return count


def execute_sql(db_path: str | Path, sql: str, *, backup: bool = True) -> tuple[list[str], list[tuple[Any, ...]], str]:
    statement = (sql or "").strip()
    if not statement:
        return [], [], "Kein SQL-Befehl eingegeben."
    db = initialize_database(db_path)
    is_select = statement.casefold().startswith(("select", "pragma", "with"))
    if not is_select and backup:
        backup_database(db, "pre_sql")
    with closing(_connect(db)) as conn:
        with conn:
            if is_select:
                cur = conn.execute(statement)
                columns = [desc[0] for desc in cur.description or []]
                rows = [tuple(row) for row in cur.fetchall()]
                return columns, rows, f"{len(rows)} Zeile(n)."
            conn.executescript(statement)
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('updated_at', ?)", (_now(),))
            return [], [], "SQL-Änderung ausgeführt."
