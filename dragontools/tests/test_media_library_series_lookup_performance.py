from __future__ import annotations

from contextlib import closing
from pathlib import Path

from dragontools.core.media_library import initialize_database
from dragontools.core.media_library_db import _connect
from dragontools.core import media_library_path_mappings, media_library_series_paths


def _insert_series(db_path: Path, series_dir: Path, *, normalized_title: str = "kaiju no 8") -> None:
    with closing(_connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO media_items(
                    item_type, title, series_title, path, parent_path, filename,
                    normalized_title, year, analysis_status, exists_flag, active,
                    created_at, updated_at
                ) VALUES(
                    'series', 'Kaiju No. 8', NULL, ?, ?, ?, ?, 2024,
                    'storage_scan', 1, 1, '2026-09-12', '2026-09-12'
                )
                """,
                (str(series_dir), str(series_dir.parent), series_dir.name, normalized_title),
            )


def test_series_lookup_uses_one_indexed_query_for_normalized_hit(tmp_path: Path) -> None:
    db_path = initialize_database(tmp_path / "library.sqlite3")
    series_dir = tmp_path / "Anime" / "Kaiju No. 8 (2024)"
    series_dir.mkdir(parents=True)
    _insert_series(db_path, series_dir)

    statements: list[str] = []
    with closing(_connect(db_path)) as conn:
        conn.set_trace_callback(statements.append)
        rows = media_library_series_paths._series_lookup_rows(
            conn,
            target_norm="kaiju no 8",
            series_name="Kaiju No. 8",
        )

        plan = conn.execute(
            """
            EXPLAIN QUERY PLAN
            SELECT item_type, title, series_title, path, parent_path, year
            FROM media_items
            WHERE exists_flag=1
              AND active=1
              AND item_type IN (?, ?, ?, ?)
              AND normalized_title=?
            """,
            ("series", "folder", "season", "episode", "kaiju no 8"),
        ).fetchall()

    media_selects = [
        sql for sql in statements
        if sql.lstrip().upper().startswith("SELECT ITEM_TYPE") and "FROM media_items" in sql
    ]
    assert len(rows) == 1
    assert len(media_selects) == 1
    assert any("normalized_title=?" in str(row[3]) for row in plan)


def test_series_lookup_runs_only_one_legacy_fallback_query(tmp_path: Path) -> None:
    db_path = initialize_database(tmp_path / "library.sqlite3")
    series_dir = tmp_path / "Anime" / "Kaiju No. 8 (2024)"
    series_dir.mkdir(parents=True)
    _insert_series(db_path, series_dir, normalized_title="legacy-wrong-value")

    statements: list[str] = []
    with closing(_connect(db_path)) as conn:
        conn.set_trace_callback(statements.append)
        rows = media_library_series_paths._series_lookup_rows(
            conn,
            target_norm="kaiju no 8",
            series_name="Kaiju No. 8",
        )

    media_selects = [
        sql for sql in statements
        if sql.lstrip().upper().startswith("SELECT ITEM_TYPE") and "FROM media_items" in sql
    ]
    assert len(rows) == 1
    assert len(media_selects) == 2


def test_series_settings_lookup_reuses_connection_for_path_mappings(tmp_path: Path, monkeypatch) -> None:
    db_path = initialize_database(tmp_path / "library.sqlite3")
    series_dir = tmp_path / "Anime" / "Kaiju No. 8 (2024)"
    series_dir.mkdir(parents=True)
    _insert_series(db_path, series_dir)

    with closing(_connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO path_mappings(label, external_prefix, local_prefix, created_at)
                VALUES('Anime', '/Anime', ?, '2026-09-12')
                """,
                (str(series_dir.parent),),
            )

    class FakeSettings:
        values = {
            "media_library/enabled": True,
            "media_library/preflight_enabled": True,
            "media_library/db_path": str(db_path),
            "media_library/path_mappings_json": "",
        }

        def value(self, key, default=None, *, type=None):
            value = self.values.get(key, default)
            if type is bool:
                return bool(value)
            if type is str:
                return str(value)
            return value

    original_connect = media_library_series_paths._connect
    connect_calls = 0

    def counted_connect(path):
        nonlocal connect_calls
        connect_calls += 1
        return original_connect(path)

    def unexpected_mapping_connect(_path):
        raise AssertionError("Path-Mappings duerfen keine zweite DB-Verbindung oeffnen")

    monkeypatch.setattr(media_library_series_paths, "_connect", counted_connect)
    monkeypatch.setattr(media_library_path_mappings, "_connect", unexpected_mapping_connect)

    result = media_library_series_paths.find_series_dir_from_settings(
        FakeSettings(),
        "Kaiju No. 8",
        [(str(series_dir.parent), "Anime")],
        year=2024,
    )

    assert result is not None
    assert Path(result["series_dir"]) == series_dir
    assert connect_calls == 1


def test_series_lookup_reports_year_ambiguity_without_scanning_folders(tmp_path: Path) -> None:
    db_path = initialize_database(tmp_path / "library.sqlite3")
    anime_root = tmp_path / "Anime"
    old_dir = anime_root / "Ranma ½ (1989)"
    new_dir = anime_root / "Ranma ½ (2024)"
    old_dir.mkdir(parents=True)
    new_dir.mkdir(parents=True)

    with closing(_connect(db_path)) as conn:
        with conn:
            for series_dir, year in ((old_dir, 1989), (new_dir, 2024)):
                conn.execute(
                    """
                    INSERT INTO media_items(
                        item_type, title, path, parent_path, filename,
                        normalized_title, year, analysis_status, exists_flag, active,
                        created_at, updated_at
                    ) VALUES('series', 'Ranma 1/2', ?, ?, ?, 'ranma 1 2', ?,
                             'storage_scan', 1, 1, '2026-09-12', '2026-09-12')
                    """,
                    (str(series_dir), str(anime_root), series_dir.name, year),
                )

    ambiguous = media_library_series_paths.find_series_root(
        db_path,
        "Ranma 1/2",
        [(str(anime_root), "Anime")],
        require_existing=False,
    )
    resolved = media_library_series_paths.find_series_root(
        db_path,
        "Ranma 1/2",
        [(str(anime_root), "Anime")],
        require_existing=False,
        year=2024,
    )

    assert ambiguous is not None
    assert ambiguous["series_dir"] == ""
    assert ambiguous["ambiguous_years"] == "1989,2024"
    assert resolved is not None
    assert resolved["series_dir"] == str(new_dir)
