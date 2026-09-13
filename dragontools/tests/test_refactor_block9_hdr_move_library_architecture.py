from __future__ import annotations

import ast
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[1]


def _lines(relative: str) -> int:
    return len((PACKAGE / relative).read_text(encoding="utf-8").splitlines())


def _max_function_lines(relative: str) -> int:
    tree = ast.parse((PACKAGE / relative).read_text(encoding="utf-8"))
    sizes = [
        node.end_lineno - node.lineno + 1
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    return max(sizes, default=0)


def test_block9_facades_stay_small() -> None:
    assert _lines("worker/hdrplus_conversion.py") <= 240
    assert _lines("gui/move_lifecycle_coordinator.py") <= 100
    assert _lines("core/media_library_repository_items.py") <= 80


def test_block9_split_modules_exist_and_have_bounded_methods() -> None:
    modules = [
        "worker/hdrplus_helper_services.py",
        "worker/hdrplus_helper_compat.py",
        "gui/move_lifecycle_helpers.py",
        "gui/move_regular_lifecycle.py",
        "gui/move_incremental_lifecycle.py",
        "core/media_library_item_sql.py",
        "core/media_library_media_info_mapper.py",
    ]
    for relative in modules:
        assert (PACKAGE / relative).is_file(), relative
        assert _max_function_lines(relative) <= 95, relative


def test_hdrplus_service_split_remains_qt_free() -> None:
    for relative in (
        "worker/hdrplus_helper_services.py",
        "worker/hdrplus_helper_compat.py",
    ):
        source = (PACKAGE / relative).read_text(encoding="utf-8")
        assert "PyQt" not in source
        assert "PySide" not in source


def test_move_coordinator_no_longer_owns_qsettings_or_dialog_logic() -> None:
    source = (PACKAGE / "gui/move_lifecycle_coordinator.py").read_text(encoding="utf-8")
    assert "QSettings" not in source
    assert "QMessageBox" not in source
    assert "traceback" not in source


def test_media_library_item_sql_and_mapping_are_separated() -> None:
    sql_source = (PACKAGE / "core/media_library_item_sql.py").read_text(encoding="utf-8")
    mapper_source = (PACKAGE / "core/media_library_media_info_mapper.py").read_text(encoding="utf-8")
    facade_source = (PACKAGE / "core/media_library_repository_items.py").read_text(encoding="utf-8")

    assert "INSERT INTO media_items" in sql_source
    assert "MediaInfo" not in sql_source
    assert "sqlite3" not in mapper_source
    assert "INSERT INTO media_items" not in mapper_source
    assert "INSERT INTO media_items" not in facade_source


def test_move_lifecycle_pure_helpers_keep_expected_semantics() -> None:
    from dragontools.gui.move_lifecycle_helpers import (
        format_move_eta,
        input_paths_for_output,
        successful_video_sources,
    )

    assert format_move_eta(-1) == ""
    assert format_move_eta(65) == "Verschieben – noch ca. 1 min 05 s"
    assert successful_video_sources([
        {"kind": "video", "ok": True, "source_path": "a.mkv"},
        {"kind": "sidecar", "ok": True, "source_path": "a.srt"},
        {"kind": "video", "ok": False, "source_path": "b.mkv"},
    ]) == {"a.mkv"}
    assert input_paths_for_output(
        {"in.mkv": {"output_path": "out.mkv"}}, "out.mkv"
    ) == ["in.mkv"]


def test_media_info_mapper_preserves_core_item_and_stream_fields() -> None:
    from types import SimpleNamespace
    from dragontools.core.media_library_media_info_mapper import (
        _item_from_media_info,
        _streams_from_media_info,
    )

    video = SimpleNamespace(
        codec="hevc", bitrate=1_000_000, width=1920, height=1080,
        hdr_format="HDR10+", pix_fmt="yuv420p10le", bit_depth=10,
        profile="Main 10", duration_s=60.0, frame_count=1440,
        frame_rate="24/1", frame_rate_mode="CFR", color_space="bt2020nc",
        color_transfer="smpte2084", color_primaries="bt2020",
    )
    audio = SimpleNamespace(
        codec="eac3", language="deu", channels=6, channel_layout="5.1",
        bitrate=640_000, title="Deutsch",
    )
    subtitle = SimpleNamespace(
        codec="subrip", language="deu", forced=True, duration_s=59.0,
        source_kind="internal", external_path=None, title="Forced",
    )
    info = SimpleNamespace(
        video_streams=[video], audio_streams=[audio], subtitle_streams=[subtitle],
        duration_s=60.0, size_bytes=12_345_678, is_hdr=True,
        has_hdr10plus=True, dolby_vision=False, dolby_vision_profile=None,
    )

    item = _item_from_media_info("/definitely/not/existing/Movie.mkv", info)
    streams = _streams_from_media_info(info)

    assert item["normalized_title"] == "movie"
    assert item["video_codec"] == "hevc"
    assert item["has_hdr10plus"] == 1
    assert [stream["stream_type"] for stream in streams] == ["Video", "Audio", "Subtitle"]
    assert streams[1]["language"] == "deu"
    assert streams[2]["forced"] == 1


def test_media_item_sql_upsert_replaces_stream_snapshot_in_memory() -> None:
    import sqlite3
    from dragontools.core.media_library_item_sql import _insert_item

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE media_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT, item_type TEXT, title TEXT, original_title TEXT,
            series_title TEXT, season INTEGER, episode INTEGER, year INTEGER, source TEXT,
            source_id TEXT, provider TEXT, path TEXT UNIQUE, parent_path TEXT, filename TEXT,
            normalized_title TEXT, container TEXT, duration_s REAL, size_bytes INTEGER,
            width INTEGER, height INTEGER, video_codec TEXT, video_bitrate INTEGER,
            overall_bitrate INTEGER, is_hdr INTEGER, has_hdr10plus INTEGER,
            has_dolby_vision INTEGER, dv_profile TEXT, nfo_status TEXT, nfo_path TEXT,
            nfo_type TEXT, nfo_mtime REAL, nfo_scanned_at TEXT, trickplay_status TEXT,
            analysis_status TEXT, exists_flag INTEGER, active INTEGER, created_at TEXT, updated_at TEXT
        );
        CREATE TABLE media_streams(
            id INTEGER PRIMARY KEY AUTOINCREMENT, media_id INTEGER, stream_type TEXT,
            stream_index INTEGER, codec TEXT, language TEXT, forced INTEGER, channels INTEGER,
            channel_layout TEXT, bitrate INTEGER, width INTEGER, height INTEGER, hdr_format TEXT,
            dv_profile TEXT, pix_fmt TEXT, bit_depth INTEGER, profile TEXT, duration_s REAL,
            frame_count INTEGER, frame_rate TEXT, frame_rate_mode TEXT, color_space TEXT,
            color_transfer TEXT, color_primaries TEXT, source_kind TEXT, external_path TEXT, title TEXT
        );
        """
    )
    item = {
        "item_type": "video", "title": "A", "series_title": None, "season": None,
        "episode": None, "year": None, "source": "test", "source_id": None,
        "provider": None, "path": "/a.mkv", "parent_path": "/", "filename": "a.mkv",
        "normalized_title": "a", "container": "mkv", "duration_s": 1.0,
        "size_bytes": 10, "width": 1, "height": 1, "video_codec": "hevc",
        "video_bitrate": 8, "overall_bitrate": 80, "is_hdr": 0, "has_hdr10plus": 0,
        "has_dolby_vision": 0, "dv_profile": None, "nfo_status": "none",
        "trickplay_status": "none", "analysis_status": "ok",
    }
    stream = {
        "stream_type": "Video", "stream_index": 0, "codec": "hevc", "language": None,
        "forced": 0, "channels": None, "channel_layout": None, "bitrate": 8,
        "width": 1, "height": 1, "hdr_format": None, "dv_profile": None,
        "pix_fmt": None, "bit_depth": None, "title": None,
    }

    media_id = _insert_item(conn, item, [stream])
    assert media_id == 1
    assert conn.execute("SELECT COUNT(*) FROM media_streams").fetchone()[0] == 1

    item["title"] = "B"
    _insert_item(conn, item, [])
    assert conn.execute("SELECT title FROM media_items").fetchone()[0] == "B"
    assert conn.execute("SELECT COUNT(*) FROM media_streams").fetchone()[0] == 0
