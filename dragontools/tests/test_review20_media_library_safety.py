from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from dragontools.core import media_library_schema
from dragontools.core.media_library_db import (
    _INITIALIZED_DATABASE_KEYS,
    _connect,
    initialize_database,
    initialize_database_once,
)
from dragontools.core.media_library_fix_queue import (
    ACTION_OCR_BITMAP_SUBTITLE,
    MediaLibraryFixIssue,
)
from dragontools.core.media_library_item_sql import _insert_item
from dragontools.core.media_library_path_mappings import apply_path_mappings
from dragontools.core.media_library_series_paths import find_series_root
from dragontools.core.media_library_types import PathMapping
from dragontools.core.media_library_utils import _normalize_title
from dragontools.core.path_syntax import path_compare_key, path_is_same_or_child
from dragontools.worker.media_library_fix_service import MediaLibraryFixService


def _legacy_db(db: Path, *, version: int = 1) -> None:
    conn = sqlite3.connect(db)
    try:
        conn.executescript(
            """
            CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE media_items(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL UNIQUE,
                active INTEGER NOT NULL DEFAULT 1,
                exists_flag INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL DEFAULT ''
            );
            """
        )
        conn.execute("INSERT INTO meta(key, value) VALUES('schema_version', ?)", (str(version),))
        conn.commit()
    finally:
        conn.close()


def _item(path: str, title: str, *, item_type: str = "movie", series_title: str | None = None) -> dict:
    p = Path(path)
    return {
        "item_type": item_type,
        "title": title,
        "series_title": series_title,
        "season": 1 if item_type == "episode" else None,
        "episode": 1 if item_type == "episode" else None,
        "year": None,
        "source": "review20",
        "source_id": None,
        "provider": None,
        "path": path,
        "parent_path": str(p.parent),
        "filename": p.name,
        "normalized_title": _normalize_title(series_title or title),
        "container": "mkv",
        "duration_s": 60.0,
        "size_bytes": 1024,
        "width": 1920,
        "height": 1080,
        "video_codec": "hevc",
        "video_bitrate": 1_000_000,
        "overall_bitrate": 1_200_000,
        "is_hdr": 0,
        "has_hdr10plus": 0,
        "has_dolby_vision": 0,
        "dv_profile": None,
        "nfo_status": "missing",
        "trickplay_status": "missing",
        "analysis_status": "ok",
    }


def test_interrupted_migration_rolls_back_schema_and_journal_mode(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "legacy.sqlite3"
    _legacy_db(db, version=1)
    with sqlite3.connect(db) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].casefold() == "delete"

    def fail_indexes(_conn):
        raise RuntimeError("synthetic migration interruption")

    monkeypatch.setattr(media_library_schema, "_create_indexes", fail_indexes)
    with pytest.raises(RuntimeError, match="synthetic migration interruption"):
        initialize_database(db)

    with sqlite3.connect(db) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(media_items)")}
        version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0].casefold()
    assert "title" not in columns
    assert "path_key" not in columns
    assert version == "1"
    assert journal == "delete"


def test_future_schema_rejection_does_not_change_database_settings(tmp_path: Path) -> None:
    db = tmp_path / "future.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO meta(key, value) VALUES('schema_version', '999')")
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.commit()

    with pytest.raises(media_library_schema.UnsupportedMediaLibrarySchemaError):
        initialize_database(db)

    with sqlite3.connect(db) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].casefold() == "delete"
        assert conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "999"


def test_windows_case_variants_upsert_one_active_logical_item(tmp_path: Path) -> None:
    db = initialize_database(tmp_path / "library.sqlite3")
    with closing(_connect(db)) as conn:
        with conn:
            first = _insert_item(conn, _item(r"C:\Media\Movie.mkv", "First"), [])
            second = _insert_item(conn, _item(r"c:\media\MOVIE.mkv", "Second"), [])
        rows = conn.execute(
            "SELECT id, path, path_key, title, active, exists_flag FROM media_items ORDER BY id"
        ).fetchall()

    assert first == second
    assert len(rows) == 1
    assert rows[0]["title"] == "Second"
    assert rows[0]["path_key"] == path_compare_key(r"C:\Media\Movie.mkv")
    assert rows[0]["active"] == 1


def test_migrated_inactive_case_duplicate_cannot_block_rescan(tmp_path: Path) -> None:
    db = initialize_database(tmp_path / "library.sqlite3")
    with closing(_connect(db)) as conn:
        with conn:
            active_id = _insert_item(conn, _item(r"C:\Media\Movie.mkv", "Active"), [])
            base = conn.execute("SELECT * FROM media_items WHERE id=?", (active_id,)).fetchone()
            columns = [row[1] for row in conn.execute("PRAGMA table_info(media_items)")]
            values = {column: base[column] for column in columns}
            values["id"] = None
            values["path"] = r"c:\media\MOVIE.mkv"
            values["path_key"] = path_compare_key(values["path"])
            values["title"] = "Historical"
            values["active"] = 0
            names = [name for name in columns if name != "id"]
            conn.execute(
                f"INSERT INTO media_items({','.join(names)}) VALUES({','.join('?' for _ in names)})",
                tuple(values[name] for name in names),
            )
        with conn:
            rescanned_id = _insert_item(conn, _item(r"c:\media\MOVIE.mkv", "Rescanned"), [])
        rows = conn.execute("SELECT id, title, active FROM media_items ORDER BY id").fetchall()

    assert rescanned_id == active_id
    assert len(rows) == 2
    assert [row["active"] for row in rows] == [1, 0]
    assert rows[0]["title"] == "Rescanned"


def test_schema_migration_preserves_duplicate_rows_but_deactivates_extra_windows_identity(tmp_path: Path) -> None:
    db = tmp_path / "legacy_duplicates.sqlite3"
    _legacy_db(db, version=6)
    with sqlite3.connect(db) as conn:
        conn.executemany(
            "INSERT INTO media_items(path, active, exists_flag, updated_at) VALUES(?,1,1,?)",
            [
                (r"C:\Media\Movie.mkv", "2026-01-01T00:00:00"),
                (r"c:\media\MOVIE.mkv", "2026-02-01T00:00:00"),
            ],
        )
        conn.commit()

    initialize_database(db)
    with closing(_connect(db)) as conn:
        rows = conn.execute(
            "SELECT id, path, path_key, active FROM media_items ORDER BY id"
        ).fetchall()

    assert len(rows) == 2
    assert {row["path_key"] for row in rows} == {path_compare_key(r"C:\Media\Movie.mkv")}
    assert sum(int(row["active"]) for row in rows) == 1
    assert rows[1]["active"] == 1  # newest updated_at wins


def test_unicode_series_title_remains_searchable(tmp_path: Path) -> None:
    db = initialize_database(tmp_path / "library.sqlite3")
    title = "劇場版モノノ怪"
    media_path = "/Anime/劇場版モノノ怪/Staffel 01/劇場版モノノ怪 - S01E01.mkv"
    with closing(_connect(db)) as conn:
        with conn:
            _insert_item(conn, _item(media_path, title, item_type="episode", series_title=title), [])

    result = find_series_root(db, title, require_existing=False)
    assert result is not None
    assert result["series_dir"].replace("\\", "/").endswith("/Anime/劇場版モノノ怪")


def test_posix_mapping_is_case_sensitive(tmp_path: Path) -> None:
    local_root = tmp_path / "Anime"
    mapping = PathMapping("Anime", "/Anime", str(local_root))

    exact = apply_path_mappings("/Anime/Show/file.mkv", [mapping])
    wrong_case = apply_path_mappings("/anime/Show/file.mkv", [mapping])

    assert path_is_same_or_child(exact, local_root)
    assert not path_is_same_or_child(wrong_case, local_root)


def test_mapping_rejects_parent_traversal_that_escapes_external_root(tmp_path: Path) -> None:
    local_root = tmp_path / "Anime"
    mapping = PathMapping("Anime", "/Anime", str(local_root))

    assert apply_path_mappings("/Anime/../Secrets/file.mkv", [mapping]) == ""


@pytest.mark.skipif(os.name == "nt", reason="POSIX case-sensitive filesystem identity test")
def test_initialize_once_does_not_casefold_distinct_posix_database_paths(tmp_path: Path) -> None:
    _INITIALIZED_DATABASE_KEYS.clear()
    upper = tmp_path / "Library.sqlite3"
    lower = tmp_path / "library.sqlite3"

    initialize_database_once(upper)
    initialize_database_once(lower)

    assert upper.is_file()
    assert lower.is_file()
    assert upper != lower


def test_track_bound_fix_rejects_file_changed_after_discovery(tmp_path: Path) -> None:
    media = tmp_path / "episode.mkv"
    media.write_bytes(b"first")
    issue = MediaLibraryFixIssue(
        media_id=1,
        path=str(media),
        title="Episode",
        item_type="episode",
        issue_type="bitmap_subtitle",
        action=ACTION_OCR_BITMAP_SUBTITLE,
        problem="PGS OCR",
        action_label="OCR",
        stream_id=10,
        stream_index=3,
        stream_type="subtitle",
        codec="hdmv_pgs_subtitle",
    )
    media.write_bytes(b"changed-and-longer")

    service = MediaLibraryFixService.__new__(MediaLibraryFixService)
    service.worker = None
    service._ocr_bitmap_subtitle = lambda _issue: pytest.fail("stale stream index reached OCR")

    result = service.execute(issue)
    assert result.status == "skipped"
    assert "geändert" in result.message


def test_duplicate_episode_search_enriches_only_duplicate_rows(tmp_path: Path, monkeypatch) -> None:
    from dragontools.core import media_library_search_service as search_service

    db = initialize_database(tmp_path / "library.sqlite3")
    now = "2026-10-05T00:00:00"
    with closing(_connect(db)) as conn, conn:
        rows = []
        for season in range(1, 11):
            for episode in range(1, 51):
                filename = f"Show - S{season:02d}E{episode:02d}.mkv"
                path = f"/TV/Show/Staffel {season:02d}/{filename}"
                rows.append((
                    "episode", "Show", "Show", season, episode, path,
                    f"/TV/Show/Staffel {season:02d}", filename, "show", 1, 1, now, now,
                ))
        # One additional file with the same logical S01E01 identity.
        rows.append((
            "episode", "Show", "Show", 1, 1,
            "/TV/Show/Staffel 01/Show - S01E01 - duplicate.mkv",
            "/TV/Show/Staffel 01", "Show - S01E01 - duplicate.mkv", "show", 1, 1, now, now,
        ))
        conn.executemany(
            """
            INSERT INTO media_items(
                item_type, title, series_title, season, episode, path, parent_path,
                filename, normalized_title, exists_flag, active, created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            rows,
        )

    enriched_batch_sizes: list[int] = []
    original = search_service.enrich_search_rows_with_streams

    def tracking_enrich(conn, rows):
        enriched_batch_sizes.append(len(rows))
        return original(conn, rows)

    monkeypatch.setattr(search_service, "enrich_search_rows_with_streams", tracking_enrich)
    result = search_service.search_library(db, "duplicate_active_sxxexx", limit=500)

    assert len(result) == 2
    assert enriched_batch_sizes
    assert max(enriched_batch_sizes) == 2


def test_manual_mutating_sql_script_rolls_back_all_statements_on_error(tmp_path: Path) -> None:
    from dragontools.core.media_library_db import execute_sql

    db = initialize_database(tmp_path / "library.sqlite3")
    with pytest.raises(sqlite3.OperationalError, match="missing_table"):
        execute_sql(
            db,
            "CREATE TABLE partial_commit_probe(id INTEGER); "
            "INSERT INTO missing_table VALUES(1);",
            backup=False,
        )

    with sqlite3.connect(db) as conn:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='partial_commit_probe'"
        ).fetchone()
    assert exists is None


def test_invalid_nfo_clears_stale_valid_type_and_mtime_but_keeps_path(tmp_path: Path) -> None:
    from dragontools.core.media_library_nfo_scan import scan_nfo_inventory

    media_dir = tmp_path / "Movie"
    media_dir.mkdir()
    media = media_dir / "Movie.mkv"
    media.write_bytes(b"video")
    nfo = media_dir / "movie.nfo"
    nfo.write_text("<movie><title>Movie</title></movie>", encoding="utf-8")
    db = initialize_database(tmp_path / "library.sqlite3")
    with closing(_connect(db)) as conn, conn:
        media_id = _insert_item(conn, _item(str(media), "Movie"), [])

    first = scan_nfo_inventory(db, backup=False)
    assert first.nfo_present == 1
    with closing(_connect(db)) as conn:
        before = conn.execute(
            "SELECT nfo_type, nfo_mtime FROM media_items WHERE id=?", (media_id,)
        ).fetchone()
    assert before["nfo_type"] == "movie"
    assert before["nfo_mtime"] is not None

    nfo.write_text("<!DOCTYPE movie [<!ENTITY xxe SYSTEM 'file:///etc/passwd'>]><movie>&xxe;</movie>", encoding="utf-8")
    second = scan_nfo_inventory(db, backup=False)
    assert second.nfo_invalid == 1
    with closing(_connect(db)) as conn:
        after = conn.execute(
            "SELECT nfo_status, nfo_path, nfo_type, nfo_mtime FROM media_items WHERE id=?",
            (media_id,),
        ).fetchone()
    assert after["nfo_status"] == "invalid"
    assert Path(after["nfo_path"]) == nfo
    assert after["nfo_type"] is None
    assert after["nfo_mtime"] is None


def test_text_search_casefolds_unicode_original_titles(tmp_path: Path) -> None:
    from dragontools.core.media_library_search_service import search_library

    db = initialize_database(tmp_path / "library.sqlite3")
    row = _item("/Movies/Berserk.mkv", "Berserk")
    row["original_title"] = "БЕРСЕРК"
    with closing(_connect(db)) as conn, conn:
        _insert_item(conn, row, [])
        _insert_item(conn, _item("/Movies/Unrelated.mkv", "Unrelated"), [])

    result = search_library(db, text="берсерк", limit=50)
    assert len(result) == 1
    assert result[0]["title"] == "Berserk"


def test_storage_rebuild_does_not_replace_library_when_any_root_is_unreachable(tmp_path: Path) -> None:
    from dragontools.core.media_library_scan import scan_storage_paths_to_database

    db = initialize_database(tmp_path / "library.sqlite3")
    with closing(_connect(db)) as conn, conn:
        _insert_item(conn, _item("/Existing/Keep.mkv", "Keep"), [])

    reachable = tmp_path / "reachable"
    reachable.mkdir()
    missing = tmp_path / "missing-nas-root"
    result = scan_storage_paths_to_database(
        db,
        [
            PathMapping("Filme", "/FilmeA", str(reachable)),
            PathMapping("Filme", "/FilmeB", str(missing)),
        ],
        replace_existing=True,
    )

    assert result.aborted is True
    assert result.skipped_roots == 1
    with closing(_connect(db)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM media_items WHERE title='Keep'").fetchone()[0] == 1


def test_incremental_storage_scan_abort_rolls_back_partial_items_and_mappings(tmp_path: Path) -> None:
    from dragontools.core.media_library_scan import scan_storage_paths_to_database

    db = initialize_database(tmp_path / "library.sqlite3")
    with closing(_connect(db)) as conn, conn:
        _insert_item(conn, _item("/Existing/Keep.mkv", "Keep"), [])
        conn.execute(
            "INSERT INTO path_mappings(label, external_prefix, local_prefix, created_at) VALUES(?,?,?,?)",
            ("Old", "/Old", "/old", "2026-01-01T00:00:00"),
        )

    root = tmp_path / "movies"
    root.mkdir()
    (root / "A.mkv").write_bytes(b"a")
    (root / "B.mkv").write_bytes(b"b")
    checks = 0

    def should_abort() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 2

    def failing_analyzer(_path, _tools):
        raise RuntimeError("synthetic analyzer failure")

    result = scan_storage_paths_to_database(
        db,
        [PathMapping("Filme", "/Filme", str(root))],
        replace_existing=False,
        analyzer=failing_analyzer,
        should_abort=should_abort,
    )

    assert result.aborted is True
    with closing(_connect(db)) as conn:
        rows = conn.execute("SELECT title, path FROM media_items ORDER BY id").fetchall()
        mappings = conn.execute(
            "SELECT label, external_prefix, local_prefix FROM path_mappings ORDER BY id"
        ).fetchall()
    assert [(row["title"], row["path"]) for row in rows] == [("Keep", "/Existing/Keep.mkv")]
    assert [tuple(row) for row in mappings] == [("Old", "/Old", "/old")]
