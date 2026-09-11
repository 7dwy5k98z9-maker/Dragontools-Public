from __future__ import annotations

from pathlib import Path
import sqlite3

from dragontools.core.media_library_types import LibraryStats, PathMapping
from dragontools.core.settings import (
    DEFAULT_MEDIA_LIBRARY_ANALYZE_ON_IMPORT,
    DEFAULT_MEDIA_LIBRARY_ENABLED,
    DEFAULT_MEDIA_LIBRARY_PREFLIGHT_ENABLED,
    SET_KEY_MEDIA_LIBRARY_ANALYZE_ON_IMPORT,
    SET_KEY_MEDIA_LIBRARY_DB_PATH,
    SET_KEY_MEDIA_LIBRARY_ENABLED,
    SET_KEY_MEDIA_LIBRARY_LAST_JELLYFIN_DB,
    SET_KEY_MEDIA_LIBRARY_PATH_MAPPINGS,
    SET_KEY_MEDIA_LIBRARY_PREFLIGHT_ENABLED,
    SET_KEY_PATH_ANIME,
    SET_KEY_PATH_FILME,
    SET_KEY_PATH_H265_ANIME,
    SET_KEY_PATH_H265_FILME,
    SET_KEY_PATH_H265_TV,
    SET_KEY_PATH_TV,
)
from dragontools.gui.media_library_dialog_presenter import MediaLibraryDialogPresenter
from dragontools.gui.media_library_dialog_service import MediaLibraryDialogService, MediaLibraryDialogState


class FakeSettings:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.sync_count = 0

    def value(self, key, default=None, type=None):
        value = self.values.get(key, default)
        if type is bool:
            return bool(value)
        if type is str:
            return str(value)
        return value

    def setValue(self, key, value):
        self.values[key] = value

    def sync(self):
        self.sync_count += 1


def test_dialog_service_loads_defaults_and_storage_mapping():
    settings = FakeSettings({
        SET_KEY_PATH_H265_ANIME: r"D:\Anime",
        SET_KEY_PATH_H265_TV: r"D:\TV",
        SET_KEY_PATH_H265_FILME: r"D:\Filme",
    })
    state = MediaLibraryDialogService().load_state(settings)

    assert state.enabled is DEFAULT_MEDIA_LIBRARY_ENABLED
    assert state.preflight_enabled is DEFAULT_MEDIA_LIBRARY_PREFLIGHT_ENABLED
    assert state.analyze_on_import is DEFAULT_MEDIA_LIBRARY_ANALYZE_ON_IMPORT
    assert [(m.label, m.external_prefix, m.local_prefix) for m in state.mappings] == [
        ("Anime", "/Anime", r"D:\Anime"),
        ("TV", "/TVSerien", r"D:\TV"),
        ("Filme", "/Filme", r"D:\Filme"),
    ]


def test_dialog_service_roundtrips_settings_state():
    settings = FakeSettings()
    service = MediaLibraryDialogService()
    state = MediaLibraryDialogState(
        enabled=True,
        preflight_enabled=False,
        analyze_on_import=True,
        db_path=r"D:\DragonTools\library.sqlite3",
        jellyfin_db_path=r"D:\Jellyfin\library.db",
        mappings=(PathMapping("Anime", "/Anime", r"D:\Anime"),),
    )
    service.save_state(settings, state)
    loaded = service.load_state(settings)

    assert loaded.enabled is True
    assert loaded.preflight_enabled is False
    assert loaded.analyze_on_import is True
    assert loaded.db_path == state.db_path
    assert loaded.jellyfin_db_path == state.jellyfin_db_path
    assert loaded.mappings == state.mappings
    assert settings.sync_count == 1


def test_storage_path_mapping_prefers_h265_then_fallback():
    settings = FakeSettings({
        SET_KEY_PATH_H265_ANIME: r"D:\Anime-H265",
        SET_KEY_PATH_ANIME: r"D:\Anime",
        SET_KEY_PATH_TV: r"D:\TV",
        SET_KEY_PATH_H265_FILME: "",
        SET_KEY_PATH_FILME: r"D:\Filme",
    })
    mappings = MediaLibraryDialogService.storage_path_mappings(settings)
    assert mappings == [
        PathMapping("Anime", "/Anime", r"D:\Anime-H265"),
        PathMapping("TV", "/TVSerien", r"D:\TV"),
        PathMapping("Filme", "/Filme", r"D:\Filme"),
    ]


def test_sql_mutation_detection_is_conservative_for_non_plain_select():
    service = MediaLibraryDialogService()
    assert service.sql_is_mutating("SELECT * FROM media_items") is False
    assert service.sql_is_mutating(" pragma table_info(media_items)") is True
    assert service.sql_is_mutating("WITH q AS (SELECT 1) SELECT * FROM q") is True
    assert service.sql_is_mutating("UPDATE media_items SET active=0") is True




def test_search_csv_export_ignores_gui_500_row_limit(tmp_path):
    from dragontools.core.media_library import initialize_database

    db_path = initialize_database(tmp_path / "library.sqlite3")
    rows = [
        (
            f"Film {index:04d}",
            str(tmp_path / "Filme" / f"Film {index:04d}.mkv"),
            str(tmp_path / "Filme"),
            f"Film {index:04d}.mkv",
            "2026-09-11",
            "2026-09-11",
        )
        for index in range(525)
    ]
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO media_items(title, path, parent_path, filename, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    service = MediaLibraryDialogService()
    displayed = service.search(
        str(db_path),
        "all",
        "",
        scope="all",
        media_type="all",
    )
    assert len(displayed) == 500

    target, exported_count = service.export_search_csv(
        str(db_path),
        "all",
        "",
        str(tmp_path / "all_results.csv"),
        scope="all",
        media_type="all",
    )

    assert exported_count == 525
    assert len(Path(target).read_text(encoding="utf-8-sig").splitlines()) == 526


def test_presenter_formats_stats_without_gui_dependency(tmp_path):
    stats = LibraryStats(
        db_path=tmp_path / "library.sqlite3",
        schema_version=2,
        media_count=12,
        active_count=10,
        inactive_count=2,
        movie_count=3,
        series_count=2,
        episode_count=7,
        stream_count=25,
        updated_at="2026-09-02T18:00:00",
    )
    text = MediaLibraryDialogPresenter.format_stats(stats)
    assert "12 Einträge (10 aktiv, 2 inaktiv)" in text
    assert "Filme: 3, Serien: 2, Episoden: 7" in text
    assert "Schema: 2" in text


def test_presenter_search_row_keeps_dv_hdr_priority():
    row = {
        "item_type": "episode",
        "title": "Folge 10",
        "series_title": "American Dad!",
        "season": 22,
        "episode": 10,
        "year": 2026,
        "video_codec": "hevc",
        "width": 1920,
        "height": 1080,
        "has_dolby_vision": 1,
        "has_hdr10plus": 1,
        "is_hdr": 1,
        "size_bytes": 2 * 1024 * 1024 * 1024,
        "duration_s": 3661,
        "path": r"D:\TV\American Dad.mkv",
    }
    values = MediaLibraryDialogPresenter.search_row_values(row, "all")
    assert values[6] == "hevc (DV, HDR10+)"
    assert values[7] == "1920x1080"
    assert values[10] is None  # NFO status
    assert values[11] is None  # NFO issue level
    assert values[12] == "1:01:01"
    assert values[13] == "2.00 GiB"
    assert values[3:6] == [22, 10, 2026]


def test_saved_queries_and_dynamic_schema_help(tmp_path):
    from dragontools.core.media_library import initialize_database

    db_path = initialize_database(tmp_path / "library.sqlite3")
    service = MediaLibraryDialogService()

    service.save_named_query(
        str(db_path),
        "sql",
        "Episoden ohne NFO",
        {"sql": "SELECT * FROM media_items WHERE item_type='episode' AND nfo_status='missing'"},
    )
    service.save_named_query(
        str(db_path),
        "search",
        "NFO Fehler",
        {"preset": "nfo_errors", "text": "", "scope": "all", "media_type": "all"},
    )

    stored = service.load_saved_queries(str(db_path))
    assert stored["sql"][0]["name"] == "Episoden ohne NFO"
    assert stored["search"][0]["preset"] == "nfo_errors"

    help_text = service.schema_help(str(db_path))
    assert "SQL-Schnellhilfe" in help_text
    assert "### media_items" in help_text
    assert "`original_title`" in help_text
    assert "### media_provider_ids" in help_text
    assert "### nfo_issues" in help_text
    assert "SELECT ... FROM ..." in help_text

    exported = service.export_schema_help(str(db_path), tmp_path / "schema.md")
    assert Path(exported).read_text(encoding="utf-8") == help_text

    service.delete_named_query(str(db_path), "sql", "Episoden ohne NFO")
    assert service.load_saved_queries(str(db_path))["sql"] == []
