from __future__ import annotations

import sqlite3

from .media_library_migrations import _ensure_media_items_schema, _ensure_media_streams_schema
from .media_library_types import SCHEMA_VERSION


def _create_schema(conn: sqlite3.Connection) -> None:
    """Create/migrate the schema in a migration-safe order.

    Tables are created first, then missing legacy columns are added, and only
    afterwards are indexes created.  This is important for older DragonTools
    databases where an index may reference a column that did not yet exist.
    """
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
            original_title TEXT,
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
            nfo_path TEXT,
            nfo_type TEXT,
            nfo_mtime REAL,
            nfo_scanned_at TEXT,
            trickplay_status TEXT NOT NULL DEFAULT 'unknown',
            analysis_status TEXT NOT NULL DEFAULT 'unknown',
            exists_flag INTEGER NOT NULL DEFAULT 1,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

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
            source_kind TEXT NOT NULL DEFAULT 'internal',
            external_path TEXT,
            title TEXT
        );

        CREATE TABLE IF NOT EXISTS media_provider_ids (
            media_id INTEGER NOT NULL REFERENCES media_items(id) ON DELETE CASCADE,
            provider TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(media_id, provider)
        );

        CREATE TABLE IF NOT EXISTS metadata_values (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            value TEXT NOT NULL,
            normalized_value TEXT NOT NULL,
            UNIQUE(kind, normalized_value)
        );
        CREATE TABLE IF NOT EXISTS media_item_values (
            media_id INTEGER NOT NULL REFERENCES media_items(id) ON DELETE CASCADE,
            value_id INTEGER NOT NULL REFERENCES metadata_values(id) ON DELETE CASCADE,
            sort_order INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(media_id, value_id)
        );

        CREATE TABLE IF NOT EXISTS people (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT,
            name TEXT NOT NULL,
            UNIQUE(source_id)
        );
        CREATE TABLE IF NOT EXISTS media_people (
            media_id INTEGER NOT NULL REFERENCES media_items(id) ON DELETE CASCADE,
            person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
            role_type TEXT NOT NULL DEFAULT '',
            character_name TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(media_id, person_id, role_type, character_name)
        );

        CREATE TABLE IF NOT EXISTS collections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            source_id TEXT NOT NULL,
            name TEXT NOT NULL,
            UNIQUE(source, source_id)
        );
        CREATE TABLE IF NOT EXISTS collection_members (
            collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
            media_id INTEGER NOT NULL REFERENCES media_items(id) ON DELETE CASCADE,
            sort_order INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(collection_id, media_id)
        );

        CREATE TABLE IF NOT EXISTS nfo_metadata (
            media_id INTEGER PRIMARY KEY REFERENCES media_items(id) ON DELETE CASCADE,
            title TEXT,
            original_title TEXT,
            series_title TEXT,
            season INTEGER,
            episode INTEGER,
            year INTEGER,
            runtime_minutes INTEGER,
            parse_status TEXT NOT NULL DEFAULT 'unknown',
            parse_error TEXT,
            parsed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS nfo_provider_ids (
            media_id INTEGER NOT NULL REFERENCES media_items(id) ON DELETE CASCADE,
            provider TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            PRIMARY KEY(media_id, provider)
        );

        CREATE TABLE IF NOT EXISTS nfo_issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            media_id INTEGER NOT NULL REFERENCES media_items(id) ON DELETE CASCADE,
            severity TEXT NOT NULL,
            field TEXT NOT NULL,
            db_value TEXT,
            nfo_value TEXT,
            message TEXT NOT NULL,
            checked_at TEXT NOT NULL
        );
        """
    )

    # Legacy migrations must happen before any index references new columns.
    _ensure_media_items_schema(conn)
    _ensure_media_streams_schema(conn)
    _create_indexes(conn)

    current = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    if current is None or str(current["value"]) != str(SCHEMA_VERSION):
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )


def _create_indexes(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_media_items_title ON media_items(normalized_title);
        CREATE INDEX IF NOT EXISTS idx_media_items_series ON media_items(series_title);
        CREATE INDEX IF NOT EXISTS idx_media_items_type ON media_items(item_type);
        CREATE INDEX IF NOT EXISTS idx_media_items_path ON media_items(path);
        CREATE INDEX IF NOT EXISTS idx_media_items_parent ON media_items(parent_path);
        CREATE INDEX IF NOT EXISTS idx_media_items_video ON media_items(video_codec, width, height);
        CREATE INDEX IF NOT EXISTS idx_media_items_active_episode
            ON media_items(active, item_type, parent_path, season, episode);
        CREATE INDEX IF NOT EXISTS idx_media_items_series_lookup
            ON media_items(active, exists_flag, item_type, normalized_title, year);
        CREATE INDEX IF NOT EXISTS idx_media_items_movie_lookup
            ON media_items(active, exists_flag, item_type, normalized_title, year, parent_path);
        CREATE INDEX IF NOT EXISTS idx_media_items_size ON media_items(size_bytes);

        CREATE INDEX IF NOT EXISTS idx_media_streams_media ON media_streams(media_id);
        CREATE INDEX IF NOT EXISTS idx_media_streams_media_type ON media_streams(media_id, stream_type);
        CREATE INDEX IF NOT EXISTS idx_media_streams_type_lang ON media_streams(stream_type, language);
        CREATE INDEX IF NOT EXISTS idx_media_streams_type_codec ON media_streams(stream_type, codec);

        CREATE INDEX IF NOT EXISTS idx_media_provider_lookup
            ON media_provider_ids(provider, provider_id);
        CREATE INDEX IF NOT EXISTS idx_metadata_values_kind_value
            ON metadata_values(kind, normalized_value);
        CREATE INDEX IF NOT EXISTS idx_media_people_media ON media_people(media_id);
        CREATE INDEX IF NOT EXISTS idx_collection_members_media ON collection_members(media_id);
        CREATE INDEX IF NOT EXISTS idx_nfo_provider_lookup
            ON nfo_provider_ids(provider, provider_id);
        CREATE INDEX IF NOT EXISTS idx_nfo_issues_media ON nfo_issues(media_id);
        CREATE INDEX IF NOT EXISTS idx_nfo_issues_severity ON nfo_issues(severity);
        """
    )
