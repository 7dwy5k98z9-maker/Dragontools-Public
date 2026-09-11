from __future__ import annotations

import sqlite3
from contextlib import contextmanager, closing
from pathlib import Path

import pytest


@contextmanager
def _db_connection(path):
    """SQLite-Testverbindung transaktional verwenden und garantiert schließen."""
    with closing(sqlite3.connect(path)) as conn:
        with conn:
            yield conn


from dragontools.core.media_library import (
    PathMapping,
    apply_path_mappings,
    backup_database,
    cleanup_inactive_media_items,
    describe_series_path_resolution,
    execute_sql,
    export_database,
    export_database_to_csv,
    export_search_results_to_csv,
    find_series_root,
    get_stats,
    import_jellyfin_database,
    initialize_database,
    normalize_database_stream_types,
    record_moved_file,
    scan_storage_paths_to_database,
    search_library,
)
from dragontools.core.models import AudioStream, MediaInfo, SubtitleStream, VideoStream
from dragontools.core.paths import path_compare_key


def test_backup_database_contains_committed_wal_data(tmp_path):
    db_path = initialize_database(tmp_path / "dragontools.sqlite3")

    # Writer absichtlich offen halten und Auto-Checkpoint deaktivieren, damit
    # commitete Daten nachweisbar noch im WAL liegen koennen.
    with _db_connection(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_autocheckpoint=0")
        conn.execute("CREATE TABLE wal_probe (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO wal_probe(value) VALUES ('committed-in-wal')")
        conn.commit()

        wal_path = Path(f"{db_path}-wal")
        assert wal_path.exists()
        assert wal_path.stat().st_size > 0

        backup_path = backup_database(db_path, "wal_probe")

    assert backup_path is not None and backup_path.exists()
    with _db_connection(backup_path) as backup_conn:
        row = backup_conn.execute("SELECT value FROM wal_probe").fetchone()
    assert row == ("committed-in-wal",)


def test_database_export_contains_committed_wal_data(tmp_path):
    db_path = initialize_database(tmp_path / "dragontools.sqlite3")
    export_dir = tmp_path / "export"

    with _db_connection(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_autocheckpoint=0")
        conn.execute("CREATE TABLE wal_export_probe (value TEXT NOT NULL)")
        conn.execute("INSERT INTO wal_export_probe(value) VALUES ('export-from-wal')")
        conn.commit()

        wal_path = Path(f"{db_path}-wal")
        assert wal_path.exists() and wal_path.stat().st_size > 0
        exported = export_database(db_path, export_dir)

    with _db_connection(exported) as exported_conn:
        row = exported_conn.execute("SELECT value FROM wal_export_probe").fetchone()
    assert row == ("export-from-wal",)


def test_backup_database_removes_partial_snapshot_after_backup_failure(tmp_path, monkeypatch):
    from dragontools.core import media_library_db as db_module

    db_path = initialize_database(tmp_path / "dragontools.sqlite3")
    created_destinations: list[Path] = []

    def fail_online_backup(_source: Path, destination: Path) -> None:
        created_destinations.append(destination)
        destination.write_bytes(b"partial-invalid-backup")
        raise sqlite3.OperationalError("simulierter Backupfehler")

    monkeypatch.setattr(db_module, "_online_backup_database", fail_online_backup)

    with pytest.raises(sqlite3.OperationalError, match="simulierter Backupfehler"):
        db_module.backup_database(db_path, "failure_injection")

    assert len(created_destinations) == 1
    assert not created_destinations[0].exists()


def test_write_action_does_not_continue_when_database_backup_fails(tmp_path, monkeypatch):
    from dragontools.core import media_library_db as db_module

    db_path = initialize_database(tmp_path / "dragontools.sqlite3")

    def fail_backup(*_args, **_kwargs):
        raise OSError("disk full during backup")

    monkeypatch.setattr(db_module, "backup_database", fail_backup)

    with pytest.raises(OSError, match="disk full during backup"):
        db_module.execute_sql(db_path, "CREATE TABLE must_not_be_created(id INTEGER)", backup=True)

    with _db_connection(db_path) as conn:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='must_not_be_created'"
        ).fetchone()
    assert exists is None


def _create_minimal_jellyfin_db(path: Path) -> None:
    with _db_connection(path) as conn:
        conn.execute(
            """
            CREATE TABLE TypedBaseItems (
                Guid TEXT,
                Type TEXT,
                Name TEXT,
                Path TEXT,
                SeriesName TEXT,
                ParentIndexNumber INTEGER,
                IndexNumber INTEGER,
                ProductionYear INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE MediaStreams (
                ItemId TEXT,
                StreamType TEXT,
                Codec TEXT,
                Language TEXT,
                Channels INTEGER,
                BitRate INTEGER,
                Width INTEGER,
                Height INTEGER,
                IsForced INTEGER,
                VideoRange TEXT,
                DvProfile TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO TypedBaseItems
            VALUES (
                'episode-1',
                'MediaBrowser.Controller.Entities.TV.Episode',
                'Wegweisende Originalitaet',
                '/Anime/Iron Wok Jan (2026)/Staffel 01/Iron Wok Jan - S01E09.mkv',
                'Iron Wok Jan',
                1,
                9,
                2026
            )
            """
        )
        conn.execute(
            """
            INSERT INTO TypedBaseItems
            VALUES (
                'movie-1',
                'MediaBrowser.Controller.Entities.Movies.Movie',
                'Beispiel Film',
                '/Filme/B/Beispiel Film (2026)/Beispiel Film (2026).mkv',
                NULL,
                NULL,
                NULL,
                2026
            )
            """
        )
        conn.executemany(
            "INSERT INTO MediaStreams VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("episode-1", "Video", "hevc", None, None, 2_500_000, 1920, 1080, 0, "HDR10", None),
                ("episode-1", "Audio", "eac3", "deu", 6, 640_000, None, None, 0, None, None),
                ("episode-1", "Subtitle", "srt", "deu", None, None, None, None, 1, None, None),
                ("movie-1", "Video", "h264", None, None, 8_000_000, 3840, 2160, 0, "SDR", None),
                ("movie-1", "Audio", "aac", "eng", 2, 192_000, None, None, 0, None, None),
            ],
        )


def _fake_media_info(path: str, _tools=None, **_kwargs) -> MediaInfo:
    file_path = Path(path)
    is_hdrplus = "hdrplus" in file_path.stem.casefold()
    return MediaInfo(
        path=path,
        audio_streams=[
            AudioStream(
                index=1,
                language="deu",
                forced=False,
                title="Deutsch",
                codec="eac3",
                channels=6,
                bitrate=640000,
            )
        ],
        subtitle_streams=[
            SubtitleStream(
                index=2,
                language="deu",
                forced=True,
                title="Forced",
                codec="subrip",
            )
        ],
        video_streams=[
            VideoStream(
                index=0,
                codec="hevc",
                width=3840 if is_hdrplus else 1920,
                height=2160 if is_hdrplus else 1080,
                hdr_format="hdr10plus" if is_hdrplus else "hdr10",
                has_hdr10plus=is_hdrplus,
                bit_depth=10,
                pix_fmt="yuv420p10le",
                profile="Main 10",
                duration_s=1420.0,
                frame_count=34046,
                frame_rate="24000/1001",
                frame_rate_mode="CFR",
                color_space="bt2020nc",
                color_transfer="smpte2084",
                color_primaries="bt2020",
                bitrate=2_500_000,
            )
        ],
        duration_s=1420.0,
        size_bytes=123456789,
        is_hdr=True,
        has_hdr10plus=is_hdrplus,
        analysis_source="Test",
    )


def test_video_bitrate_uses_stream_size_when_embedded_bps_tag_is_broken() -> None:
    from dragontools.core.media_analyzer_streams import _build_video_streams

    streams = _build_video_streams(
        [
            {
                "Format": "HEVC",
                "Width": "1920",
                "Height": "1080",
                "Duration": "1441.023",
                "BitRate": "651",
                "StreamSize": "350099251",
            }
        ],
        [{}],
        {},
        [],
    )

    assert len(streams) == 1
    assert streams[0].bitrate == round((350_099_251 * 8) / 1441.023)


def test_path_mapping_translates_jellyfin_prefix(tmp_path: Path) -> None:
    local = tmp_path / "Serien" / "Anime"
    mapped = apply_path_mappings(
        "/Anime/Iron Wok Jan (2026)/Staffel 01/Folge.mkv",
        [PathMapping("Anime", "/Anime", str(local))],
    )

    assert "Iron Wok Jan (2026)" in mapped
    assert mapped.endswith(str(Path("Staffel 01") / "Folge.mkv"))
    assert str(local) in mapped


def test_import_jellyfin_database_builds_dragon_library(tmp_path: Path) -> None:
    jellyfin_db = tmp_path / "library.db"
    target_db = tmp_path / "dragontools.sqlite3"
    _create_minimal_jellyfin_db(jellyfin_db)
    anime_root = tmp_path / "video" / "Serien" / "Anime"
    film_root = tmp_path / "video" / "Filme"

    result = import_jellyfin_database(
        jellyfin_db,
        target_db,
        [
            PathMapping("Anime", "/Anime", str(anime_root)),
            PathMapping("Filme", "/Filme", str(film_root)),
        ],
    )

    stats = get_stats(target_db)
    assert result.imported_items == 2
    assert result.imported_streams == 5
    assert stats.media_count == 2
    assert stats.episode_count == 1
    assert stats.movie_count == 1


def test_jellyfin_import_normalizes_stream_types_to_dragon_schema(tmp_path: Path) -> None:
    jellyfin_db = tmp_path / "library.db"
    target_db = tmp_path / "dragontools.sqlite3"
    with _db_connection(jellyfin_db) as conn:
        conn.execute(
            """
            CREATE TABLE TypedBaseItems (
                Guid TEXT, Type TEXT, Name TEXT, Path TEXT, SeriesName TEXT,
                ParentIndexNumber INTEGER, IndexNumber INTEGER, ProductionYear INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE MediaStreams (
                ItemId TEXT, StreamType TEXT, Codec TEXT, Language TEXT, Channels INTEGER,
                BitRate INTEGER, Width INTEGER, Height INTEGER, IsForced INTEGER,
                VideoRange TEXT, DvProfile TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO TypedBaseItems
            VALUES (
                'episode-1',
                'MediaBrowser.Controller.Entities.TV.Episode',
                'Folge',
                '/Anime/Test (2026)/Staffel 01/Test - S01E01.mkv',
                'Test',
                1,
                1,
                2026
            )
            """
        )
        conn.executemany(
            "INSERT INTO MediaStreams VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("episode-1", "1", "hevc", None, None, 2_500_000, 1920, 1080, 0, "bt709", None),
                ("episode-1", 0, "eac3", "deu", 6, 640_000, None, None, 0, None, None),
                ("episode-1", "2", "subrip", "deu", None, None, None, None, 1, None, None),
            ],
        )

    import_jellyfin_database(
        jellyfin_db,
        target_db,
        [PathMapping("Anime", "/Anime", str(tmp_path / "video" / "Anime"))],
    )

    with _db_connection(target_db) as conn:
        stream_types = [row[0] for row in conn.execute("SELECT stream_type FROM media_streams ORDER BY id")]

    assert stream_types == ["Video", "Audio", "Subtitle"]


def test_jellyfin_import_preserves_explicit_hdr10plus_flags(tmp_path: Path) -> None:
    jellyfin_db = tmp_path / "library.db"
    target_db = tmp_path / "dragontools.sqlite3"
    with _db_connection(jellyfin_db) as conn:
        conn.execute(
            """
            CREATE TABLE TypedBaseItems (
                Guid TEXT, Type TEXT, Name TEXT, Path TEXT, SeriesName TEXT,
                ParentIndexNumber INTEGER, IndexNumber INTEGER, ProductionYear INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE MediaStreams (
                ItemId TEXT, StreamType TEXT, Codec TEXT, Language TEXT, Channels INTEGER,
                BitRate INTEGER, Width INTEGER, Height INTEGER, IsForced INTEGER,
                VideoRange TEXT, DvProfile TEXT, Hdr10PlusPresentFlag INTEGER
            )
            """
        )
        conn.execute(
            """
            INSERT INTO TypedBaseItems
            VALUES (
                'movie-1',
                'MediaBrowser.Controller.Entities.Movies.Movie',
                'HDR Plus Film',
                '/Filme/HDR Plus Film (2026)/HDR Plus Film (2026).mkv',
                NULL,
                NULL,
                NULL,
                2026
            )
            """
        )
        conn.execute(
            "INSERT INTO MediaStreams VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("movie-1", "Video", "hevc", None, None, 10_000_000, 3840, 2160, 0, "smpte2084", None, 1),
        )

    import_jellyfin_database(
        jellyfin_db,
        target_db,
        [PathMapping("Filme", "/Filme", str(tmp_path / "video" / "Filme"))],
    )

    rows = search_library(target_db, "hdr10plus", scope="movies", media_type="videos")
    assert [row["title"] for row in rows] == ["HDR Plus Film"]
    assert rows[0]["has_hdr10plus"] == 1


def test_jellyfin_import_supports_current_baseitems_media_stream_infos_schema(tmp_path: Path) -> None:
    jellyfin_db = tmp_path / "jellyfin.db"
    target_db = tmp_path / "dragontools.sqlite3"
    with _db_connection(jellyfin_db) as conn:
        conn.execute(
            """
            CREATE TABLE BaseItems (
                Id TEXT PRIMARY KEY,
                Type TEXT NOT NULL,
                Name TEXT,
                Path TEXT,
                SeriesName TEXT,
                SeriesId TEXT,
                ParentIndexNumber INTEGER,
                IndexNumber INTEGER,
                ProductionYear INTEGER,
                RunTimeTicks INTEGER,
                Size INTEGER,
                TotalBitrate INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE MediaStreamInfos (
                ItemId TEXT,
                StreamIndex INTEGER,
                StreamType INTEGER,
                Codec TEXT,
                Language TEXT,
                Channels INTEGER,
                ChannelLayout TEXT,
                BitRate INTEGER,
                Width INTEGER,
                Height INTEGER,
                IsForced INTEGER,
                ColorPrimaries TEXT,
                ColorTransfer TEXT,
                DvProfile INTEGER,
                RpuPresentFlag INTEGER,
                Hdr10PlusPresentFlag INTEGER,
                PixelFormat TEXT,
                BitDepth INTEGER,
                Title TEXT
            )
            """
        )
        conn.executemany(
            "INSERT INTO BaseItems VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "series-1", "MediaBrowser.Controller.Entities.TV.Series", "Testserie",
                    "/Anime/Testserie (2026)", None, None, None, None, 2026, None, None, None,
                ),
                (
                    "season-1", "MediaBrowser.Controller.Entities.TV.Season", "Staffel 2",
                    "/Anime/Testserie (2026)/Staffel 02", None, "series-1", None, 2, 2026,
                    None, None, None,
                ),
                (
                    "episode-1", "MediaBrowser.Controller.Entities.TV.Episode", "Dolby-Folge",
                    "/Anime/Testserie (2026)/Staffel 02/Testserie - S02E03.mkv", None, "series-1",
                    2, 3, 2026, 18_000_000_000, 1_234_567_890, 18_500_000,
                ),
                (
                    "movie-1", "MediaBrowser.Controller.Entities.Movies.Movie", "SDR-Film",
                    "/Filme/S/SDR-Film (2025)/SDR-Film (2025).mp4", None, None, None, None,
                    2025, 54_000_000_000, 2_345_678_901, 9_500_000,
                ),
                (
                    "person-1", "MediaBrowser.Controller.Entities.Person", "Nicht importieren",
                    "%MetadataPath%/People/N/Nicht importieren/folder.jpg", None, None, None,
                    None, None, None, None, None,
                ),
            ],
        )
        conn.executemany(
            "INSERT INTO MediaStreamInfos VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("episode-1", 0, 1, "hevc", None, None, None, 17_000_000, 3840, 1608, 0,
                 "bt2020", "smpte2084", 8, 1, 0, "yuv420p10le", 10, None),
                ("episode-1", 1, 0, "eac3", "jpn", 6, "5.1", 640_000, None, None, 0,
                 None, None, None, 0, 0, None, None, "Japanisch"),
                ("episode-1", 2, 2, "ass", "deu", None, None, None, None, None, 1,
                 None, None, None, 0, 0, None, None, "Deutsch Forced"),
                ("movie-1", 0, 1, "h264", None, None, None, 9_000_000, 1920, 1080, 0,
                 "bt709", "bt709", None, 0, 0, "yuv420p", 8, None),
                ("movie-1", 1, 0, "aac", "eng", 2, "stereo", 192_000, None, None, 0,
                 None, None, None, 0, 0, None, None, "English"),
            ],
        )

    result = import_jellyfin_database(
        jellyfin_db,
        target_db,
        [
            PathMapping("Anime", "/Anime", str(tmp_path / "video" / "Anime")),
            PathMapping("Filme", "/Filme", str(tmp_path / "video" / "Filme")),
        ],
    )

    assert result.imported_items == 4
    assert result.imported_streams == 5
    assert result.skipped_items == 1
    with _db_connection(target_db) as conn:
        conn.row_factory = sqlite3.Row
        episode = conn.execute("SELECT * FROM media_items WHERE source_id='episode-1'").fetchone()
        season = conn.execute("SELECT * FROM media_items WHERE source_id='season-1'").fetchone()
        movie = conn.execute("SELECT * FROM media_items WHERE source_id='movie-1'").fetchone()
        episode_streams = conn.execute(
            "SELECT stream_type, codec, language, forced, bitrate, hdr_format, dv_profile "
            "FROM media_streams WHERE media_id=? ORDER BY stream_index",
            (episode["id"],),
        ).fetchall()
        movie_video = conn.execute(
            "SELECT hdr_format FROM media_streams WHERE media_id=? AND stream_type='Video'",
            (movie["id"],),
        ).fetchone()

    assert episode["series_title"] == "Testserie"
    assert episode["season"] == 2
    assert episode["episode"] == 3
    assert episode["container"] == "mkv"
    assert episode["duration_s"] == 1800.0
    assert episode["overall_bitrate"] == 18_500_000
    assert episode["width"] == 3840
    assert episode["height"] == 1608
    assert episode["video_codec"] == "hevc"
    assert episode["video_bitrate"] == 17_000_000
    assert episode["is_hdr"] == 1
    assert episode["has_dolby_vision"] == 1
    assert episode["has_hdr10plus"] == 0
    assert season["series_title"] == "Testserie"
    assert season["season"] == 2
    assert movie["container"] == "mp4"
    assert movie["overall_bitrate"] == 9_500_000
    assert movie["is_hdr"] == 0
    assert [tuple(row[:5]) for row in episode_streams] == [
        ("Video", "hevc", None, 0, 17_000_000),
        ("Audio", "eac3", "jpn", 0, 640_000),
        ("Subtitle", "ass", "deu", 1, None),
    ]
    assert "Dolby Vision" in episode_streams[0]["hdr_format"]
    assert episode_streams[0]["dv_profile"] == "8"
    assert "SDR" in movie_video["hdr_format"]


def test_jellyfin_import_deduplicates_equivalent_windows_paths(tmp_path: Path) -> None:
    jellyfin_db = tmp_path / "jellyfin.db"
    target_db = tmp_path / "dragontools.sqlite3"
    with _db_connection(jellyfin_db) as conn:
        conn.execute(
            """
            CREATE TABLE BaseItems (
                Id TEXT, Type TEXT, Name TEXT, Path TEXT, ProductionYear INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE MediaStreamInfos (
                ItemId TEXT, StreamIndex INTEGER, StreamType INTEGER, Codec TEXT,
                Width INTEGER, Height INTEGER, ColorTransfer TEXT
            )
            """
        )
        conn.executemany(
            "INSERT INTO BaseItems VALUES (?, ?, ?, ?, ?)",
            [
                (
                    "movie-1", "MediaBrowser.Controller.Entities.Movies.Movie", "Testfilm",
                    "/Filme/Testfilm/Testfilm.mkv", 2026,
                ),
                (
                    "movie-2", "MediaBrowser.Controller.Entities.Movies.Movie", "TESTFILM",
                    "/Filme/TESTFILM/TESTFILM.MKV", 2026,
                ),
            ],
        )

    result = import_jellyfin_database(
        jellyfin_db,
        target_db,
        [PathMapping("Filme", "/Filme", r"X:\Video\Filme")],
    )

    assert result.imported_items == 1
    assert result.skipped_items == 1
    assert get_stats(target_db).media_count == 1


def test_storage_scan_builds_library_from_real_folder_structure(tmp_path: Path) -> None:
    db_path = tmp_path / "dragontools.sqlite3"
    anime_root = tmp_path / "video" / "Serien" / "Anime"
    movie_root = tmp_path / "video" / "Filme"
    episode = anime_root / "Iron Wok Jan (2026)" / "Staffel 01" / "Iron Wok Jan - S01E09 - Folge.mkv"
    movie = movie_root / "HDRPlus Film (2026)" / "HDRPlus Film (2026).mkv"
    episode.parent.mkdir(parents=True)
    movie.parent.mkdir(parents=True)
    episode.write_bytes(b"video")
    movie.write_bytes(b"video")

    result = scan_storage_paths_to_database(
        db_path,
        [
            PathMapping("Anime", "/Anime", str(anime_root)),
            PathMapping("Filme", "/Filme", str(movie_root)),
        ],
        analyzer=_fake_media_info,
    )

    stats = get_stats(db_path)
    assert result.scanned_files == 2
    assert result.failed_files == 0
    assert stats.movie_count == 1
    assert stats.series_count == 1
    assert stats.episode_count == 1
    assert [row["title"] for row in search_library(db_path, "hdr10plus", scope="movies", media_type="videos")] == [
        "HDRPlus Film (2026)"
    ]
    assert [row["title"] for row in search_library(db_path, "has_german_audio", scope="anime", media_type="episodes")] == [
        "Iron Wok Jan - S01E09 - Folge"
    ]
    found = find_series_root(db_path, "Iron Wok Jan", [(str(anime_root), "anime")], require_existing=True)
    assert found is not None
    assert found["series_dir"].endswith(str(Path("Iron Wok Jan (2026)")))


def test_storage_scan_keeps_file_when_analysis_fails(tmp_path: Path) -> None:
    db_path = tmp_path / "dragontools.sqlite3"
    anime_root = tmp_path / "video" / "Serien" / "Anime"
    ok_file = anime_root / "Testserie (2026)" / "Staffel 01" / "Testserie - S01E01 - OK.mkv"
    broken_file = anime_root / "Testserie (2026)" / "Staffel 01" / "Testserie - S01E02 - Defekt.mkv"
    ok_file.parent.mkdir(parents=True)
    ok_file.write_bytes(b"video")
    broken_file.write_bytes(b"broken")

    def analyzer(path: str, _tools=None, **_kwargs) -> MediaInfo:
        if Path(path).name == broken_file.name:
            raise RuntimeError("MediaInfo konnte den Container nicht lesen")
        return _fake_media_info(path)

    result = scan_storage_paths_to_database(
        db_path,
        [PathMapping("Anime", "/Anime", str(anime_root))],
        analyzer=analyzer,
    )

    rows = search_library(db_path, "all", scope="anime", media_type="episodes")
    failed_rows = search_library(db_path, "metadata_incomplete", scope="anime", media_type="episodes")

    assert result.scanned_files == 2
    assert result.failed_files == 1
    assert result.imported_items >= 2
    assert [row["episode"] for row in rows] == [1, 2]
    assert [row["title"] for row in failed_rows] == ["Testserie - S01E02 - Defekt"]
    assert failed_rows[0]["analysis_status"] == "analysis_failed"
    assert failed_rows[0]["video_codec"] is None


def test_storage_scan_abort_keeps_existing_database(tmp_path: Path) -> None:
    db_path = initialize_database(tmp_path / "dragontools.sqlite3")
    with _db_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO media_items(
                item_type, title, path, parent_path, filename, normalized_title,
                nfo_status, trickplay_status, analysis_status, created_at, updated_at
            )
            VALUES('movie', 'Bestehender Film', ?, ?, 'Bestehender Film.mkv', 'bestehender film',
                   'unknown', 'unknown', 'ok', 'now', 'now')
            """,
            (str(tmp_path / "Bestehender Film.mkv"), str(tmp_path)),
        )
    scan_root = tmp_path / "scan"
    video = scan_root / "Neuer Film (2026).mkv"
    video.parent.mkdir()
    video.write_bytes(b"video")

    result = scan_storage_paths_to_database(
        db_path,
        [PathMapping("Filme", "/Filme", str(scan_root))],
        analyzer=_fake_media_info,
        should_abort=lambda: True,
    )

    assert result.aborted is True
    assert [row["title"] for row in search_library(db_path, "all", media_type="movies")] == ["Bestehender Film"]


def test_import_jellyfin_database_skips_unmapped_metadata_paths_when_mapping_exists(tmp_path: Path) -> None:
    jellyfin_db = tmp_path / "library.db"
    target_db = tmp_path / "dragontools.sqlite3"
    with _db_connection(jellyfin_db) as conn:
        conn.execute(
            """
            CREATE TABLE TypedBaseItems (
                Guid TEXT, Type TEXT, Name TEXT, Path TEXT, SeriesName TEXT,
                ParentIndexNumber INTEGER, IndexNumber INTEGER, ProductionYear INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE MediaStreams (
                ItemId TEXT, StreamType TEXT, Codec TEXT, Language TEXT, Channels INTEGER,
                BitRate INTEGER, Width INTEGER, Height INTEGER, IsForced INTEGER,
                VideoRange TEXT, DvProfile TEXT
            )
            """
        )
        conn.executemany(
            "INSERT INTO TypedBaseItems VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "episode-1",
                    "MediaBrowser.Controller.Entities.TV.Episode",
                    "Folge",
                    "/Anime/Test/Staffel 01/Test - S01E01.mkv",
                    "Test",
                    1,
                    1,
                    2026,
                ),
                (
                    "person-1",
                    "MediaBrowser.Controller.Entities.Person",
                    "Person",
                    "%MetadataPath%/People/P/Person",
                    None,
                    None,
                    None,
                    None,
                ),
            ],
        )

    result = import_jellyfin_database(
        jellyfin_db,
        target_db,
        [PathMapping("Anime", "/Anime", str(tmp_path / "video" / "Anime"))],
    )

    assert result.imported_items == 1
    assert result.skipped_items == 1


def test_jellyfin_import_keeps_generic_video_and_movies_namespace_out_of_movie_episode_counts(
    tmp_path: Path,
) -> None:
    jellyfin_db = tmp_path / "jellyfin.db"
    target_db = tmp_path / "dragontools.sqlite3"
    with _db_connection(jellyfin_db) as conn:
        conn.execute(
            """
            CREATE TABLE TypedBaseItems (
                Guid TEXT,
                Type TEXT,
                Name TEXT,
                Path TEXT,
                SeriesName TEXT,
                ParentIndexNumber INTEGER,
                IndexNumber INTEGER,
                ProductionYear INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE MediaStreams (
                ItemId TEXT, StreamType TEXT, Codec TEXT, Language TEXT, Channels INTEGER,
                BitRate INTEGER, Width INTEGER, Height INTEGER, IsForced INTEGER,
                VideoRange TEXT, DvProfile TEXT
            )
            """
        )
        conn.executemany(
            "INSERT INTO TypedBaseItems VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "movie-1",
                    "MediaBrowser.Controller.Entities.Movies.Movie",
                    "Echter Film",
                    "/Filme/Echter Film (2026)/Echter Film (2026).mkv",
                    None, None, None, 2026,
                ),
                (
                    "episode-1",
                    "MediaBrowser.Controller.Entities.TV.Episode",
                    "Echte Folge",
                    "/Serien/Test/Staffel 01/Test - S01E01.mkv",
                    "Test", 1, 1, 2026,
                ),
                (
                    "generic-video",
                    "MediaBrowser.Controller.Entities.Video",
                    "Bonusvideo mit Episodenmuster",
                    "/Serien/Test/Extras/Test - S01E99.mkv",
                    "Test", None, None, 2026,
                ),
                (
                    "boxset-1",
                    "MediaBrowser.Controller.Entities.Movies.BoxSet",
                    "Sammlung",
                    "/Filme/Sammlungen/Test Collection",
                    None, None, None, None,
                ),
            ],
        )

    result = import_jellyfin_database(jellyfin_db, target_db)
    stats = get_stats(target_db)

    assert result.imported_items == 3
    assert result.skipped_items == 1
    assert stats.movie_count == 1
    assert stats.episode_count == 1

    with _db_connection(target_db) as conn:
        types = dict(conn.execute("SELECT source_id, item_type FROM media_items"))
    assert types["generic-video"] == "video"
    assert "boxset-1" not in types


def test_search_and_series_root_use_imported_library(tmp_path: Path) -> None:
    jellyfin_db = tmp_path / "library.db"
    target_db = tmp_path / "dragontools.sqlite3"
    _create_minimal_jellyfin_db(jellyfin_db)
    anime_root = tmp_path / "video" / "Serien" / "Anime"
    film_root = tmp_path / "video" / "Filme"
    import_jellyfin_database(
        jellyfin_db,
        target_db,
        [
            PathMapping("Anime", "/Anime", str(anime_root)),
            PathMapping("Filme", "/Filme", str(film_root)),
        ],
    )

    no_german_audio = search_library(target_db, "no_german_audio")
    assert [row["title"] for row in no_german_audio] == ["Beispiel Film"]

    match = find_series_root(target_db, "Iron Wok Jan", [(str(anime_root), "Anime")])
    assert match is not None
    assert match["base_type"] == "Anime"
    assert match["series_dir"].endswith(str(Path("Iron Wok Jan (2026)")))


def test_series_root_uses_year_to_disambiguate_duplicate_series_names(tmp_path: Path) -> None:
    db_path = initialize_database(tmp_path / "dragontools.sqlite3")
    anime_root = tmp_path / "Anime"
    old_dir = anime_root / "Ranma ½ (1989)"
    new_dir = anime_root / "Ranma ½ (2024)"
    old_dir.mkdir(parents=True)
    new_dir.mkdir(parents=True)

    with _db_connection(db_path) as conn:
        for year, path in ((1989, old_dir), (2024, new_dir)):
            conn.execute(
                """
                INSERT INTO media_items(
                    item_type, title, path, parent_path, filename, normalized_title, year,
                    analysis_status, exists_flag, created_at, updated_at
                ) VALUES('series', ?, ?, ?, ?, ?, ?, 'storage_scan', 1, '2026-09-09', '2026-09-09')
                """,
                ("Ranma ½", str(path), str(anime_root), path.name, "ranma 1 2", year),
            )

    match = find_series_root(
        db_path,
        "Ranma 1/2",
        [(str(anime_root), "Anime")],
        require_existing=True,
        year=2024,
    )

    assert match is not None
    assert Path(match["series_dir"]) == new_dir


def test_series_root_reapplies_mapping_and_can_require_existing_path(tmp_path: Path) -> None:
    db_path = initialize_database(tmp_path / "dragontools.sqlite3")
    external_root = "/video/Serien/TV"
    local_root = tmp_path / "nas" / "video" / "Serien" / "TV"
    series_dir = local_root / "Special Ops - Lioness (2023)"
    series_dir.mkdir(parents=True)

    with _db_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO media_items(
                item_type, title, series_title, path, parent_path, filename, normalized_title,
                analysis_status, exists_flag, created_at, updated_at
            ) VALUES('series', ?, ?, ?, ?, ?, ?, 'jellyfin', 1, '2026-08-31', '2026-08-31')
            """,
            (
                "Special Ops: Lioness",
                None,
                f"{external_root}/Special Ops - Lioness (2023)",
                external_root,
                "Special Ops - Lioness (2023)",
                "special ops lioness",
            ),
        )

    match = find_series_root(
        db_path,
        "Special Ops Lioness",
        [(str(local_root), "TV")],
        mappings=[PathMapping("TV", external_root, str(local_root))],
        require_existing=True,
    )
    assert match is not None
    assert match["source"] == "database"
    assert match["base_type"] == "TV"
    assert Path(match["series_dir"]) == series_dir

    series_dir.rmdir()
    assert (
        find_series_root(
            db_path,
            "Special Ops Lioness",
            [(str(local_root), "TV")],
            mappings=[PathMapping("TV", external_root, str(local_root))],
            require_existing=True,
        )
        is None
    )


def test_series_root_rebases_old_local_db_path_to_current_storage_path(tmp_path: Path) -> None:
    db_path = initialize_database(tmp_path / "dragontools.sqlite3")
    old_root = tmp_path / "old_nas" / "Anime"
    current_root = tmp_path / "current_nas" / "Anime"
    current_series = current_root / "Iron Wok Jan (2026)"
    current_series.mkdir(parents=True)

    with _db_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO media_items(
                item_type, title, series_title, path, parent_path, filename, normalized_title,
                analysis_status, exists_flag, created_at, updated_at
            ) VALUES('series', ?, ?, ?, ?, ?, ?, 'storage_scan', 1, '2026-09-01', '2026-09-01')
            """,
            (
                "Iron Wok Jan",
                None,
                str(old_root / "Iron Wok Jan (2026)"),
                str(old_root),
                "Iron Wok Jan (2026)",
                "iron wok jan",
            ),
        )

    match = find_series_root(
        db_path,
        "Iron Wok Jan",
        [(str(current_root), "Anime")],
        mappings=[PathMapping("Anime", "/Anime", str(current_root))],
        stored_mappings=[PathMapping("Anime", "/Anime", str(old_root))],
        require_existing=True,
    )

    assert match is not None
    assert Path(match["series_dir"]) == current_series
    assert match["base"] == str(current_root)
    assert match["mapping_note"] == "rebased_from_persisted_mapping"
    assert "Alter DB-Speicherpfad" in match["mapping_notice"]
    assert "Anime-Pfad-Mapping" in match["mapping_notice"]


def test_series_path_resolution_notices_distinguish_mapping_reasons() -> None:
    assert "entspricht" in describe_series_path_resolution("", "TV")
    assert "Jellyfin-/DB-Pfad" in describe_series_path_resolution("external_to_current", "TV")
    assert "TV-Pfad-Mapping" in describe_series_path_resolution("external_to_current", "TV")
    assert "in der Mediathek gespeicherte" in describe_series_path_resolution("stored_mapping", "Anime")
    assert "Alter DB-Speicherpfad" in describe_series_path_resolution(
        "rebased_from_persisted_mapping", "Anime"
    )
    assert "Ordnernamens" in describe_series_path_resolution(
        "rebased_from_series_folder_name", "TV"
    )


def test_series_root_reports_unusable_database_path_when_current_storage_does_not_match(tmp_path: Path) -> None:
    db_path = initialize_database(tmp_path / "dragontools.sqlite3")
    old_root = tmp_path / "old_nas" / "TV"
    current_root = tmp_path / "current_nas" / "TV"
    current_root.mkdir(parents=True)

    with _db_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO media_items(
                item_type, title, series_title, path, parent_path, filename, normalized_title,
                analysis_status, exists_flag, created_at, updated_at
            ) VALUES('series', ?, ?, ?, ?, ?, ?, 'jellyfin', 1, '2026-09-01', '2026-09-01')
            """,
            (
                "Stargate Atlantis",
                None,
                str(old_root / "Stargate Atlantis (2004)"),
                str(old_root),
                "Stargate Atlantis (2004)",
                "stargate atlantis",
            ),
        )

    match = find_series_root(
        db_path,
        "Stargate Atlantis",
        [(str(current_root), "TV")],
        mappings=[PathMapping("TV", "/TVSerien", str(current_root))],
        require_existing=True,
        include_unusable=True,
    )

    assert match is not None
    assert match["series_dir"] == ""
    assert "Mediathek-Treffer" in match["unusable_reason"]


def test_series_root_unusable_match_keeps_database_area_when_default_base_differs(tmp_path: Path) -> None:
    db_path = initialize_database(tmp_path / "dragontools.sqlite3")
    current_anime = tmp_path / "current" / "Anime"
    current_tv = tmp_path / "current" / "TV"
    current_anime.mkdir(parents=True)
    current_tv.mkdir(parents=True)
    db_series_root = r"\\Medienspeicher\video\Serien\TV\Watson (2025)"

    with _db_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO media_items(
                item_type, title, series_title, path, parent_path, filename, normalized_title,
                analysis_status, exists_flag, created_at, updated_at
            ) VALUES('series', ?, ?, ?, ?, ?, ?, 'storage_scan', 1, '2026-09-01', '2026-09-01')
            """,
            (
                "Watson",
                None,
                db_series_root,
                r"\\Medienspeicher\video\Serien\TV",
                "Watson (2025)",
                "watson",
            ),
        )

    match = find_series_root(
        db_path,
        "Watson",
        [(str(current_anime), "Anime"), (str(current_tv), "TV")],
        require_existing=True,
        include_unusable=True,
    )

    assert match is not None
    assert match["series_dir"] == ""
    assert match["base"] == str(current_tv)
    assert match["base_type"] == "TV"
    assert match["suggested_series_name"] == "Watson (2025)"
    assert "Anime" not in match["unusable_reason"]


def test_manual_sql_updates_are_backed_by_schema(tmp_path: Path) -> None:
    db_path = initialize_database(tmp_path / "dragontools.sqlite3")

    columns, rows, message = execute_sql(db_path, "SELECT COUNT(*) AS count FROM media_items")

    assert columns == ["count"]
    assert rows == [(0,)]
    assert "1 Zeile" in message


def _insert_library_video(
    conn: sqlite3.Connection,
    *,
    title: str,
    path: str,
    parent_path: str,
    episode: int,
    width: int | None = 1920,
    height: int | None = 1080,
    video_codec: str | None = "hevc",
    hdr_format: str | None = "SDR",
    is_hdr: int = 0,
    has_hdr10plus: int = 0,
    has_dolby_vision: int = 0,
    analysis_status: str = "jellyfin",
    audio: tuple[tuple[str | None, str | None, int | None], ...] = (("deu", "eac3", 6),),
) -> None:
    conn.execute(
        """
        INSERT INTO media_items(
            item_type, title, series_title, season, episode, path, parent_path, filename,
            width, height, video_codec, is_hdr, has_hdr10plus, has_dolby_vision,
            analysis_status, created_at, updated_at
        ) VALUES('episode', ?, 'Testserie', 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '2026-08-31', '2026-08-31')
        """,
        (
            title,
            episode,
            path,
            parent_path,
            Path(path).name,
            width,
            height,
            video_codec,
            is_hdr,
            has_hdr10plus,
            has_dolby_vision,
            analysis_status,
        ),
    )
    media_id = int(conn.execute("SELECT id FROM media_items WHERE path=?", (path,)).fetchone()[0])
    conn.execute(
        """
        INSERT INTO media_streams(media_id, stream_type, stream_index, codec, width, height, hdr_format)
        VALUES(?, 'Video', 0, ?, ?, ?, ?)
        """,
        (media_id, video_codec, width, height, hdr_format),
    )
    for index, (language, codec, channels) in enumerate(audio):
        conn.execute(
            """
            INSERT INTO media_streams(media_id, stream_type, stream_index, codec, language, channels)
            VALUES(?, 'Audio', ?, ?, ?, ?)
            """,
            (media_id, index, codec, language, channels),
        )


def test_search_supports_resolution_buckets_and_video_codecs(tmp_path: Path) -> None:
    db_path = initialize_database(tmp_path / "dragontools.sqlite3")
    parent = str(tmp_path / "Testserie" / "Staffel 01")
    with _db_connection(db_path) as conn:
        _insert_library_video(
            conn,
            title="Cropped Full HD",
            path=str(Path(parent) / "S01E01.mkv"),
            parent_path=parent,
            episode=1,
            width=1920,
            height=800,
            video_codec="h264",
        )
        _insert_library_video(
            conn,
            title="Cropped HD",
            path=str(Path(parent) / "S01E02.mkv"),
            parent_path=parent,
            episode=2,
            width=1280,
            height=536,
            video_codec="hevc",
        )
        _insert_library_video(
            conn,
            title="Cropped UHD",
            path=str(Path(parent) / "S01E03.mkv"),
            parent_path=parent,
            episode=3,
            width=3840,
            height=1600,
            video_codec="av1",
        )

    assert [row["title"] for row in search_library(db_path, "resolution_fhd")] == ["Cropped Full HD"]
    assert [row["title"] for row in search_library(db_path, "resolution_hd")] == ["Cropped HD"]
    assert [row["title"] for row in search_library(db_path, "resolution_uhd")] == ["Cropped UHD"]
    assert [row["title"] for row in search_library(db_path, "h264")] == ["Cropped Full HD"]
    assert [row["title"] for row in search_library(db_path, "hevc")] == ["Cropped HD"]
    assert [row["title"] for row in search_library(db_path, "av1")] == ["Cropped UHD"]


def test_search_distinguishes_sdr_from_unknown_dynamic_range(tmp_path: Path) -> None:
    db_path = initialize_database(tmp_path / "dragontools.sqlite3")
    parent = str(tmp_path / "Testserie" / "Staffel 01")
    with _db_connection(db_path) as conn:
        _insert_library_video(
            conn,
            title="Explizites SDR",
            path=str(Path(parent) / "S01E01.mkv"),
            parent_path=parent,
            episode=1,
            hdr_format="SDR",
        )
        _insert_library_video(
            conn,
            title="Unbekannter Dynamikumfang",
            path=str(Path(parent) / "S01E02.mkv"),
            parent_path=parent,
            episode=2,
            hdr_format=None,
            analysis_status="jellyfin",
        )
        _insert_library_video(
            conn,
            title="HDR",
            path=str(Path(parent) / "S01E03.mkv"),
            parent_path=parent,
            episode=3,
            hdr_format="HDR10",
            is_hdr=1,
        )

    assert [row["title"] for row in search_library(db_path, "sdr")] == ["Explizites SDR"]
    assert [row["title"] for row in search_library(db_path, "dynamic_range_unknown")] == [
        "Unbekannter Dynamikumfang"
    ]
    assert [row["title"] for row in search_library(db_path, "hdr")] == ["HDR"]


def test_search_treats_jellyfin_smpte2084_as_hdr(tmp_path: Path) -> None:
    db_path = initialize_database(tmp_path / "dragontools.sqlite3")
    parent = str(tmp_path / "Testserie" / "Staffel 01")
    with _db_connection(db_path) as conn:
        _insert_library_video(
            conn,
            title="Jellyfin PQ",
            path=str(Path(parent) / "S01E01.mkv"),
            parent_path=parent,
            episode=1,
            hdr_format="smpte2084",
            is_hdr=0,
        )

    rows = search_library(db_path, "hdr")

    assert [row["title"] for row in rows] == ["Jellyfin PQ"]
    assert rows[0]["is_hdr"] == 1


def test_deviation_search_returns_only_minority_episodes(tmp_path: Path) -> None:
    db_path = initialize_database(tmp_path / "dragontools.sqlite3")
    parent = str(tmp_path / "Testserie" / "Staffel 01")
    with _db_connection(db_path) as conn:
        for episode in range(1, 13):
            audio = (("deu", "eac3", 6),) if episode <= 10 else (("jpn", "aac", 2),)
            _insert_library_video(
                conn,
                title=f"Folge {episode:02d}",
                path=str(Path(parent) / f"S01E{episode:02d}.mkv"),
                parent_path=parent,
                episode=episode,
                audio=audio,
            )

    rows = search_library(db_path, "deviation_german_audio")
    assert [row["episode"] for row in rows] == [11, 12]
    assert all("Mehrheit im Ordner: Deutsch vorhanden (10/12)" in row["deviation_reason"] for row in rows)


def test_deviation_search_marks_ties_as_uneven_without_guessing(tmp_path: Path) -> None:
    db_path = initialize_database(tmp_path / "dragontools.sqlite3")
    parent = str(tmp_path / "Testserie" / "Staffel 01")
    with _db_connection(db_path) as conn:
        for episode in range(1, 5):
            audio = (("deu", "eac3", 6),) if episode <= 2 else (("jpn", "aac", 2),)
            _insert_library_video(
                conn,
                title=f"Folge {episode:02d}",
                path=str(Path(parent) / f"S01E{episode:02d}.mkv"),
                parent_path=parent,
                episode=episode,
                audio=audio,
            )

    rows = search_library(db_path, "deviation_german_audio")
    assert len(rows) == 4
    assert all(row["deviation_reason"].startswith("Uneinheitlich – keine klare Mehrheit") for row in rows)


def test_search_supports_legacy_jellyfin_stream_types_and_scopes(tmp_path: Path) -> None:
    db_path = initialize_database(tmp_path / "dragontools.sqlite3")
    anime_root = tmp_path / "video" / "Serien" / "Anime"
    movie_root = tmp_path / "video" / "Filme"
    with _db_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO path_mappings(label, external_prefix, local_prefix, created_at) VALUES('Anime', '/Anime', ?, '2026-08-31')",
            (str(anime_root),),
        )
        conn.execute(
            "INSERT INTO path_mappings(label, external_prefix, local_prefix, created_at) VALUES('Filme', '/Filme', ?, '2026-08-31')",
            (str(movie_root),),
        )
        _insert_library_video(
            conn,
            title="Anime HDR",
            path=str(anime_root / "Serie (2026)" / "Staffel 01" / "Serie - S01E01.mkv"),
            parent_path=str(anime_root / "Serie (2026)" / "Staffel 01"),
            episode=1,
            width=None,
            height=None,
            video_codec=None,
            hdr_format=None,
            is_hdr=0,
            audio=(("deu", "eac3", 6),),
        )
        media_id = conn.execute(
            "SELECT id FROM media_items WHERE title='Anime HDR'"
        ).fetchone()[0]
        conn.execute("UPDATE media_items SET width=NULL, height=NULL, video_codec=NULL WHERE id=?", (media_id,))
        conn.execute(
            "UPDATE media_streams SET stream_type='1', codec='hevc', width=1920, height=1080, hdr_format='HDR10' WHERE media_id=? AND stream_type='Video'",
            (media_id,),
        )
        conn.execute(
            "UPDATE media_streams SET stream_type='', codec='eac3', language='deu', channels=6 WHERE media_id=? AND stream_type='Audio'",
            (media_id,),
        )
        _insert_library_video(
            conn,
            title="Film SDR",
            path=str(movie_root / "Film (2026)" / "Film (2026).mkv"),
            parent_path=str(movie_root / "Film (2026)"),
            episode=1,
            video_codec="h264",
            hdr_format="bt709",
            audio=(("eng", "aac", 2),),
        )

    assert [row["title"] for row in search_library(db_path, "has_german_audio", scope="anime")] == [
        "Anime HDR"
    ]
    assert [row["title"] for row in search_library(db_path, "hdr", scope="anime")] == ["Anime HDR"]
    assert [row["title"] for row in search_library(db_path, "sdr", scope="movies")] == ["Film SDR"]
    assert [row["title"] for row in search_library(db_path, "hevc", media_type="episodes")] == ["Anime HDR"]


def test_normalize_database_stream_types_updates_existing_library(tmp_path: Path) -> None:
    db_path = initialize_database(tmp_path / "dragontools.sqlite3")
    parent = str(tmp_path / "Testserie" / "Staffel 01")
    with _db_connection(db_path) as conn:
        _insert_library_video(
            conn,
            title="Altimport",
            path=str(Path(parent) / "S01E01.mkv"),
            parent_path=parent,
            episode=1,
        )
        media_id = conn.execute("SELECT id FROM media_items WHERE title='Altimport'").fetchone()[0]
        conn.execute(
            "UPDATE media_streams SET stream_type='1', codec='hevc', width=1920, height=1080 WHERE media_id=? AND stream_type='Video'",
            (media_id,),
        )
        conn.execute(
            "UPDATE media_streams SET stream_type='', codec='eac3', language='deu', channels=6 WHERE media_id=? AND stream_type='Audio'",
            (media_id,),
        )

    changed = normalize_database_stream_types(db_path, backup=False)

    assert changed == 2
    with _db_connection(db_path) as conn:
        stream_types = {row[0] for row in conn.execute("SELECT stream_type FROM media_streams")}
    assert {"Video", "Audio"} == stream_types


def test_media_library_csv_exports(tmp_path: Path) -> None:
    db_path = initialize_database(tmp_path / "dragontools.sqlite3")
    parent = str(tmp_path / "Testserie" / "Staffel 01")
    with _db_connection(db_path) as conn:
        _insert_library_video(
            conn,
            title="Folge",
            path=str(Path(parent) / "S01E01.mkv"),
            parent_path=parent,
            episode=1,
        )

    rows = search_library(db_path, "all")
    search_csv = export_search_results_to_csv(rows, tmp_path / "treffer.csv")
    db_csvs = export_database_to_csv(db_path, tmp_path / "csv")

    assert search_csv.exists()
    assert "Titel" in search_csv.read_text(encoding="utf-8-sig")
    overview = next(path for path in db_csvs if "_medien_uebersicht_" in path.name)
    overview_text = overview.read_text(encoding="utf-8-sig")
    assert "Bild" in overview_text
    assert "Dynamikumfang" in overview_text
    assert "Audio" in overview_text
    assert "Untertitel" in overview_text
    assert "NFO" in overview_text
    assert "Trickplay" in overview_text
    assert any(path.name.startswith("dragontools_media_items_") for path in db_csvs)
    assert any(path.name.startswith("dragontools_media_streams_") for path in db_csvs)


def test_record_moved_file_replaces_same_episode_identity(tmp_path: Path, monkeypatch) -> None:
    from dragontools.core import media_analyzer

    db_path = initialize_database(tmp_path / "dragontools.sqlite3")
    parent = tmp_path / "Testserie" / "Staffel 01"
    parent.mkdir(parents=True)
    old_path = parent / "Testserie - S01E03 - Alter Titel.mkv"
    new_path = parent / "Testserie - S01E03 - Neuer Titel.mp4"
    source_path = tmp_path / "temp" / new_path.name
    source_path.parent.mkdir()
    old_path.write_bytes(b"old")
    new_path.write_bytes(b"new")

    with _db_connection(db_path) as conn:
        _insert_library_video(
            conn,
            title="Alter Titel",
            path=str(old_path),
            parent_path=str(parent),
            episode=3,
        )
    monkeypatch.setattr(media_analyzer, "analyze_media", _fake_media_info)

    record_moved_file(db_path, source_path, new_path, replaced_paths=[old_path])

    with _db_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT filename, active, exists_flag FROM media_items WHERE season=1 AND episode=3 ORDER BY filename"
        ).fetchall()
    assert [(row[0], row[1], row[2]) for row in rows] == [
        ("Testserie - S01E03 - Alter Titel.mkv", 0, 0),
        ("Testserie - S01E03 - Neuer Titel.mp4", 1, 1),
    ]
    assert search_library(db_path, "duplicate_active_sxxexx") == []


def test_search_finds_duplicate_active_sxxexx_and_cleanup_removes_inactive(tmp_path: Path) -> None:
    db_path = initialize_database(tmp_path / "dragontools.sqlite3")
    parent = tmp_path / "Testserie" / "Staffel 01"
    with _db_connection(db_path) as conn:
        _insert_library_video(
            conn,
            title="Alter Titel",
            path=str(parent / "Testserie - S01E03 - Alter Titel.mkv"),
            parent_path=str(parent),
            episode=3,
        )
        _insert_library_video(
            conn,
            title="Neuer Titel",
            path=str(parent / "Testserie - S01E03 - Neuer Titel.mp4"),
            parent_path=str(parent),
            episode=3,
        )

    duplicates = search_library(db_path, "duplicate_active_sxxexx")

    assert {row["filename"] for row in duplicates} == {
        "Testserie - S01E03 - Alter Titel.mkv",
        "Testserie - S01E03 - Neuer Titel.mp4",
    }
    with _db_connection(db_path) as conn:
        conn.execute(
            "UPDATE media_items SET active=0, exists_flag=0 WHERE filename='Testserie - S01E03 - Alter Titel.mkv'"
        )
    removed = cleanup_inactive_media_items(db_path, backup=False)

    assert removed == 1
    with _db_connection(db_path) as conn:
        item_count = conn.execute("SELECT COUNT(*) FROM media_items").fetchone()[0]
        stream_count = conn.execute("SELECT COUNT(*) FROM media_streams").fetchone()[0]
    assert item_count == 1
    assert stream_count == 2


def test_tv_and_anime_path_mappings_use_the_same_unc_normalization() -> None:
    tv = apply_path_mappings(
        "/TVSerien/American Dad! (2005)",
        [PathMapping("TV", "/TVSerien", "//medienspeicher/video/Serien/TV")],
    )
    anime = apply_path_mappings(
        "/Anime/Test Anime (2026)",
        [PathMapping("Anime", "/Anime", r"\\Medienspeicher\video\Serien\Anime")],
    )

    assert tv == r"\\medienspeicher\video\Serien\TV\American Dad! (2005)"
    assert anime == r"\\Medienspeicher\video\Serien\Anime\Test Anime (2026)"
    assert path_compare_key(tv).startswith(path_compare_key(r"\\Medienspeicher\video\Serien\TV"))
    assert path_compare_key(anime).startswith(path_compare_key(r"\\Medienspeicher\video\Serien\Anime"))


def test_backup_database_names_are_collision_safe(tmp_path: Path) -> None:
    db_path = initialize_database(tmp_path / "dragontools.sqlite3")

    first = backup_database(db_path, "rapid")
    second = backup_database(db_path, "rapid")

    assert first is not None and second is not None
    assert first != second
    assert first.exists() and second.exists()


def test_jellyfin_import_reads_committed_wal_data_without_modifying_source(tmp_path: Path) -> None:
    jellyfin_db = tmp_path / "jellyfin" / "library.db"
    jellyfin_db.parent.mkdir()
    target_db = tmp_path / "dragon" / "dragontools.sqlite3"
    _create_minimal_jellyfin_db(jellyfin_db)

    with _db_connection(jellyfin_db) as writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0].casefold() == "wal"
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute(
            """
            INSERT INTO TypedBaseItems
            VALUES (
                'wal-movie',
                'MediaBrowser.Controller.Entities.Movies.Movie',
                'Nur im WAL',
                '/Filme/W/Nur im WAL (2026)/Nur im WAL (2026).mkv',
                NULL, NULL, NULL, 2026
            )
            """
        )
        writer.execute(
            "INSERT INTO MediaStreams VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("wal-movie", "Video", "hevc", None, None, 5_000_000, 1920, 1080, 0, "HDR10", None),
        )
        writer.commit()

        wal_path = Path(f"{jellyfin_db}-wal")
        assert wal_path.exists() and wal_path.stat().st_size > 0
        db_bytes_before = jellyfin_db.read_bytes()
        db_mtime_before = jellyfin_db.stat().st_mtime_ns

        result = import_jellyfin_database(jellyfin_db, target_db)

        # Der Snapshot darf die originale Jellyfin-Hauptdatei nicht beschreiben.
        assert jellyfin_db.read_bytes() == db_bytes_before
        assert jellyfin_db.stat().st_mtime_ns == db_mtime_before

    assert result.imported_items == 3
    with _db_connection(target_db) as conn:
        row = conn.execute(
            "SELECT title, source_id FROM media_items WHERE source_id='wal-movie'"
        ).fetchone()
    assert row == ("Nur im WAL", "wal-movie")


def test_jellyfin_import_stages_next_to_target_for_atomic_replace(tmp_path: Path, monkeypatch) -> None:
    from dragontools.core import media_library_jellyfin as jellyfin_module

    jellyfin_db = tmp_path / "source" / "library.db"
    jellyfin_db.parent.mkdir()
    _create_minimal_jellyfin_db(jellyfin_db)
    target_db = tmp_path / "target-volume" / "nested" / "dragontools.sqlite3"

    real_temporary_directory = jellyfin_module.tempfile.TemporaryDirectory
    real_replace = jellyfin_module.os.replace
    temp_dirs: list[Path] = []
    replace_calls: list[tuple[Path, Path]] = []

    def tracked_temporary_directory(*args, **kwargs):
        directory = kwargs.get("dir")
        temp_dirs.append(Path(directory) if directory is not None else Path())
        return real_temporary_directory(*args, **kwargs)

    def tracked_replace(source, destination):
        replace_calls.append((Path(source), Path(destination)))
        return real_replace(source, destination)

    monkeypatch.setattr(jellyfin_module.tempfile, "TemporaryDirectory", tracked_temporary_directory)
    monkeypatch.setattr(jellyfin_module.os, "replace", tracked_replace)

    import_jellyfin_database(jellyfin_db, target_db)

    assert temp_dirs == [target_db.parent]
    assert len(replace_calls) == 1
    staged, destination = replace_calls[0]
    assert destination == target_db
    # TemporaryDirectory wird unmittelbar in target.parent erzeugt. Damit sind
    # Staging-Datei und Ziel auf Windows-Laufwerken wie auch UNC-Shares auf
    # demselben Volume/Share und os.replace() muss keinen Volumewechsel machen.
    assert staged.parent.parent == target_db.parent


def test_jellyfin_snapshot_failure_keeps_existing_target_unchanged(tmp_path: Path, monkeypatch) -> None:
    from dragontools.core import media_library_jellyfin as jellyfin_module

    jellyfin_db = tmp_path / "jellyfin.db"
    _create_minimal_jellyfin_db(jellyfin_db)
    target_db = initialize_database(tmp_path / "dragontools.sqlite3")
    with _db_connection(target_db) as conn:
        conn.execute("CREATE TABLE preserved_marker(value TEXT NOT NULL)")
        conn.execute("INSERT INTO preserved_marker VALUES ('keep-me')")
        conn.commit()

    real_snapshot = jellyfin_module._snapshot_database

    def fail_source_snapshot(source: Path, destination: Path, **kwargs):
        if Path(source) == jellyfin_db:
            raise OSError("simulierter Jellyfin-Snapshotfehler")
        return real_snapshot(source, destination, **kwargs)

    monkeypatch.setattr(jellyfin_module, "_snapshot_database", fail_source_snapshot)

    with pytest.raises(OSError, match="Jellyfin-Snapshotfehler"):
        jellyfin_module.import_jellyfin_database(jellyfin_db, target_db)

    with _db_connection(target_db) as conn:
        row = conn.execute("SELECT value FROM preserved_marker").fetchone()
    assert row == ("keep-me",)


def test_database_schema_migrates_legacy_media_items_with_size_bytes(tmp_path: Path) -> None:
    db_path = initialize_database(tmp_path / "legacy.sqlite3")
    with _db_connection(db_path) as conn:
        conn.execute("DROP INDEX IF EXISTS idx_media_items_size")
        conn.execute("ALTER TABLE media_items DROP COLUMN size_bytes")
        for column in (
            "profile", "duration_s", "frame_count", "frame_rate", "frame_rate_mode",
            "color_space", "color_transfer", "color_primaries",
        ):
            conn.execute(f"ALTER TABLE media_streams DROP COLUMN {column}")
        conn.execute("UPDATE meta SET value='2' WHERE key='schema_version'")

    initialize_database(db_path)

    with _db_connection(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(media_items)")}
        stream_columns = {row[1] for row in conn.execute("PRAGMA table_info(media_streams)")}
        schema = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
        index_names = {row[1] for row in conn.execute("PRAGMA index_list(media_items)")}
    assert "size_bytes" in columns
    assert "idx_media_items_size" in index_names
    assert {
        "profile", "duration_s", "frame_count", "frame_rate", "frame_rate_mode",
        "color_space", "color_transfer", "color_primaries",
    } <= stream_columns
    assert schema == "5"


def test_storage_scan_records_real_file_size_and_size_filter(tmp_path: Path) -> None:
    db_path = tmp_path / "dragontools.sqlite3"
    root = tmp_path / "Filme"
    small = root / "Klein (2026).mkv"
    large = root / "Gross (2026).mkv"
    root.mkdir(parents=True)
    small.write_bytes(b"x" * 1234)
    # Sparse Datei: schnell, aber echte stat()-Groesse > 1 GiB.
    with large.open("wb") as fh:
        fh.seek((1024 ** 3) + 4095)
        fh.write(b"x")

    scan_storage_paths_to_database(
        db_path,
        [PathMapping("Filme", "/Filme", str(root))],
        analyzer=_fake_media_info,
    )

    rows = search_library(db_path, "all", media_type="videos")
    sizes = {row["filename"]: row["size_bytes"] for row in rows}
    assert sizes[small.name] == small.stat().st_size
    assert sizes[large.name] == large.stat().st_size

    with _db_connection(db_path) as conn:
        video = conn.execute(
            """
            SELECT bitrate, profile, duration_s, frame_count, frame_rate, frame_rate_mode,
                   color_space, color_transfer, color_primaries
            FROM media_streams
            WHERE stream_type='Video'
            ORDER BY id
            LIMIT 1
            """
        ).fetchone()
        item = conn.execute(
            "SELECT overall_bitrate FROM media_items WHERE filename=?", (small.name,)
        ).fetchone()
    assert video == (
        2_500_000, "Main 10", 1420.0, 34046, "24000/1001", "CFR",
        "bt2020nc", "smpte2084", "bt2020",
    )
    assert item[0] == round((small.stat().st_size * 8) / 1420.0)

    one_to_two = search_library(db_path, "size_1_2gb", media_type="videos")
    assert [row["filename"] for row in one_to_two] == [large.name]


def test_jellyfin_import_exposes_file_size_from_jellyfin_database(tmp_path: Path) -> None:
    jellyfin_db = tmp_path / "jellyfin.db"
    target_db = tmp_path / "dragontools.sqlite3"
    with _db_connection(jellyfin_db) as conn:
        conn.execute(
            """
            CREATE TABLE BaseItems (
                Id TEXT PRIMARY KEY, Type TEXT, Name TEXT, Path TEXT,
                ProductionYear INTEGER, Size INTEGER
            )
            """
        )
        conn.execute(
            """
            INSERT INTO BaseItems VALUES (
                'movie-size',
                'MediaBrowser.Controller.Entities.Movies.Movie',
                'Size Film',
                '/Filme/Size Film (2026)/Size Film (2026).mkv',
                2026,
                2345678901
            )
            """
        )

    import_jellyfin_database(
        jellyfin_db,
        target_db,
        [PathMapping("Filme", "/Filme", str(tmp_path / "video" / "Filme"))],
    )
    rows = search_library(target_db, "all", media_type="movies")
    assert len(rows) == 1
    assert rows[0]["size_bytes"] == 2_345_678_901


def test_jellyfin_duration_seconds_is_not_mistaken_for_ticks(tmp_path: Path) -> None:
    jellyfin_db = tmp_path / "jellyfin-seconds.db"
    target_db = tmp_path / "dragontools.sqlite3"
    with _db_connection(jellyfin_db) as conn:
        conn.execute(
            """
            CREATE TABLE BaseItems (
                Id TEXT PRIMARY KEY, Type TEXT, Name TEXT, Path TEXT,
                DurationSeconds REAL
            )
            """
        )
        conn.execute(
            "INSERT INTO BaseItems VALUES (?, ?, ?, ?, ?)",
            (
                "long-movie",
                "MediaBrowser.Controller.Entities.Movies.Movie",
                "Long Movie",
                "/Filme/Long Movie.mkv",
                20_001.5,
            ),
        )

    import_jellyfin_database(jellyfin_db, target_db)
    rows = search_library(target_db, "duration_over_5h", media_type="movies")
    assert len(rows) == 1
    assert rows[0]["duration_s"] == 20_001.5


def test_jellyfin_import_keeps_direct_video_stream_properties(tmp_path: Path) -> None:
    jellyfin_db = tmp_path / "jellyfin-stream-details.db"
    target_db = tmp_path / "dragontools.sqlite3"
    with _db_connection(jellyfin_db) as conn:
        conn.execute(
            """
            CREATE TABLE BaseItems (
                Id TEXT PRIMARY KEY, Type TEXT, Name TEXT, Path TEXT, RunTimeTicks INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE MediaStreamInfos (
                ItemId TEXT, StreamIndex INTEGER, StreamType INTEGER, Codec TEXT,
                AverageFrameRate REAL, RealFrameRate REAL, Profile TEXT,
                PixelFormat TEXT, BitDepth INTEGER, ColorSpace TEXT,
                ColorTransfer TEXT, ColorPrimaries TEXT, Width INTEGER, Height INTEGER,
                BitRate INTEGER
            )
            """
        )
        conn.execute(
            "INSERT INTO BaseItems VALUES (?, ?, ?, ?, ?)",
            (
                "movie-details",
                "MediaBrowser.Controller.Entities.Movies.Movie",
                "Details",
                "/Filme/Details.mkv",
                14_410_230_000,
            ),
        )
        conn.execute(
            "INSERT INTO MediaStreamInfos VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "movie-details", 0, 1, "hevc", 23.976, 23.976, "Main 10",
                "yuv420p10le", 10, "bt2020nc", "smpte2084", "bt2020",
                3840, 2160, 8_000_000,
            ),
        )

    import_jellyfin_database(jellyfin_db, target_db)
    rows = search_library(target_db, "all", media_type="movies")
    assert len(rows) == 1
    assert rows[0]["duration_s"] == pytest.approx(1441.023)
    assert rows[0]["video_profile"] == "Main 10"
    assert rows[0]["frame_rate"] == "23.976"
    assert rows[0]["frame_rate_mode"] == "CFR"
    assert rows[0]["pix_fmt"] == "yuv420p10le"
    assert rows[0]["bit_depth"] == 10
    assert rows[0]["color_space"] == "bt2020nc"
    assert rows[0]["color_transfer"] == "smpte2084"
    assert rows[0]["color_primaries"] == "bt2020"


def test_storage_scan_records_external_subtitles_nfo_and_trickplay(tmp_path: Path) -> None:
    db_path = tmp_path / "dragontools.sqlite3"
    movie_dir = tmp_path / "video" / "Filme" / "Film (2026)"
    movie_dir.mkdir(parents=True)
    video = movie_dir / "Film (2026).mkv"
    video.write_bytes(b"video")
    (movie_dir / "Film (2026).de.ass").write_text("[Script Info]\n", encoding="utf-8")
    (movie_dir / "Film (2026).de.forced.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nText\n", encoding="utf-8")
    (movie_dir / "movie.nfo").write_text("<movie />", encoding="utf-8")
    trickplay_dir = movie_dir / "Film (2026).trickplay" / "320 - 10x10"
    trickplay_dir.mkdir(parents=True)
    (trickplay_dir / "0.jpg").write_bytes(b"jpg")

    scan_storage_paths_to_database(
        db_path,
        [PathMapping("Filme", "/Filme", str(tmp_path / "video" / "Filme"))],
        analyzer=_fake_media_info,
    )

    with _db_connection(db_path) as conn:
        conn.row_factory = sqlite3.Row
        item = conn.execute("SELECT id, nfo_status, trickplay_status FROM media_items WHERE filename=?", (video.name,)).fetchone()
        subtitles = conn.execute(
            """
            SELECT codec, language, forced, source_kind, external_path
            FROM media_streams
            WHERE media_id=? AND stream_type='Subtitle'
            ORDER BY source_kind, codec
            """,
            (item["id"],),
        ).fetchall()

    assert item["nfo_status"] == "present"
    assert item["trickplay_status"] == "present"
    assert {(row["codec"], row["language"], row["source_kind"]) for row in subtitles} == {
        ("subrip", "deu", "internal"),
        ("ass", "deu", "external"),
        ("subrip", "deu", "external"),
    }
    assert any(row["forced"] == 1 and row["source_kind"] == "external" for row in subtitles)
    assert all(row["external_path"] for row in subtitles if row["source_kind"] == "external")


def test_jellyfin_import_preserves_external_subtitle_marker_when_available(tmp_path: Path) -> None:
    jellyfin_db = tmp_path / "jellyfin.db"
    target_db = tmp_path / "dragontools.sqlite3"
    with _db_connection(jellyfin_db) as conn:
        conn.execute(
            """
            CREATE TABLE BaseItems (
                Id TEXT PRIMARY KEY, Type TEXT, Name TEXT, Path TEXT,
                SeriesName TEXT, ParentIndexNumber INTEGER, IndexNumber INTEGER, ProductionYear INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE MediaStreamInfos (
                ItemId TEXT, StreamIndex INTEGER, StreamType INTEGER, Codec TEXT,
                Language TEXT, IsForced INTEGER, IsExternal INTEGER, Path TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO BaseItems VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "episode-1",
                "MediaBrowser.Controller.Entities.TV.Episode",
                "Folge",
                "/Anime/Testserie (2026)/Staffel 01/Testserie - S01E01.mkv",
                "Testserie",
                1,
                1,
                2026,
            ),
        )
        conn.executemany(
            "INSERT INTO MediaStreamInfos VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("episode-1", 0, 1, "hevc", None, 0, 0, None),
                ("episode-1", 1, 2, "ass", "deu", 0, 0, None),
                (
                    "episode-1",
                    2,
                    2,
                    "subrip",
                    "deu",
                    1,
                    1,
                    "/Anime/Testserie (2026)/Staffel 01/Testserie - S01E01.de.forced.srt",
                ),
            ],
        )

    local_root = tmp_path / "video" / "Serien" / "Anime"
    import_jellyfin_database(
        jellyfin_db,
        target_db,
        [PathMapping("Anime", "/Anime", str(local_root))],
    )

    with _db_connection(target_db) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT codec, language, forced, source_kind, external_path
            FROM media_streams
            WHERE stream_type='Subtitle'
            ORDER BY stream_index
            """
        ).fetchall()

    assert [(row["codec"], row["source_kind"]) for row in rows] == [
        ("ass", "internal"),
        ("subrip", "external"),
    ]
    assert rows[1]["forced"] == 1
    assert rows[1]["external_path"].endswith(str(Path("Testserie (2026)") / "Staffel 01" / "Testserie - S01E01.de.forced.srt"))
