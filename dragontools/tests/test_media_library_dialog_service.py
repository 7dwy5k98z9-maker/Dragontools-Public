from __future__ import annotations

from pathlib import Path

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


def test_sql_mutation_detection_keeps_existing_semantics():
    service = MediaLibraryDialogService()
    assert service.sql_is_mutating("SELECT * FROM media_items") is False
    assert service.sql_is_mutating(" pragma table_info(media_items)") is False
    assert service.sql_is_mutating("WITH q AS (SELECT 1) SELECT * FROM q") is False
    assert service.sql_is_mutating("UPDATE media_items SET active=0") is True


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
        "path": r"D:\TV\American Dad.mkv",
    }
    values = MediaLibraryDialogPresenter.search_row_values(row, "all")
    assert values[6] == "hevc (DV, HDR10+)"
    assert values[7] == "1920x1080"
    assert values[3:6] == [22, 10, 2026]
