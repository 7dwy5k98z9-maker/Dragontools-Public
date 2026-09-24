# -*- coding: utf-8 -*-
from __future__ import annotations

from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from dragontools.core.media_library_db import _connect, initialize_database
from dragontools.core.media_library_fix_queue import discover_fix_issues
from dragontools.core.nfo_stream_metadata import stage_stream_language_update
from dragontools.core.whisper_runtime import (
    build_whisper_diagnostic,
    resolve_whisper_model_reference,
    validate_local_whisper_model_dir,
)
from dragontools.worker.media_stream_metadata_guard import edit_queued_track
from dragontools.core.media_library_fix_queue import MediaLibraryFixIssue


def _nfo(path: Path, *, audio_languages=("eng", "und")) -> None:
    audio = "".join(
        f"<audio><codec>eac3</codec><language>{language}</language><channels>6</channels></audio>"
        for language in audio_languages
    )
    path.write_text(
        "<?xml version='1.0' encoding='utf-8'?>"
        f"<episodedetails><title>Episode</title><fileinfo><streamdetails>{audio}</streamdetails></fileinfo></episodedetails>",
        encoding="utf-8",
    )


def _issue(video: Path, nfo: Path) -> MediaLibraryFixIssue:
    return MediaLibraryFixIssue(
        media_id=1,
        path=str(video),
        title="Episode",
        item_type="episode",
        issue_type="stream_language_unknown",
        action="detect_stream_language",
        problem="Audio-Sprache unbekannt",
        action_label="Audio-Sprache erkennen",
        stream_id=11,
        stream_index=2,
        stream_type="audio",
        stream_ordinal=2,
        codec="eac3",
        language="und",
        track_title="",
        forced=False,
        channels=6,
        bitrate=640000,
        duration_s=1200.0,
        nfo_path=str(nfo),
    )


def test_nfo_stream_language_update_targets_matching_audio_ordinal(tmp_path: Path) -> None:
    source = tmp_path / "episode.nfo"
    target = tmp_path / "staged.nfo"
    _nfo(source)

    changed, message = stage_stream_language_update(
        source,
        target,
        stream_type="audio",
        ordinal=2,
        language="de",
    )

    assert changed
    assert "deu" in message
    text = target.read_text(encoding="utf-8")
    assert text.count("<language>eng</language>") == 1
    assert text.count("<language>deu</language>") == 1


def test_track_language_fix_updates_existing_nfo_and_video_as_one_guarded_operation(monkeypatch, tmp_path: Path) -> None:
    video = tmp_path / "Episode.mkv"
    video.write_bytes(b"original-video")
    nfo = tmp_path / "Episode.nfo"
    _nfo(nfo)
    issue = _issue(video, nfo)

    monkeypatch.setattr(
        "dragontools.worker.media_stream_metadata_guard._validate_track",
        lambda *_args, **_kwargs: None,
    )

    def fake_apply(staged_path: str, **_kwargs):
        Path(staged_path).write_bytes(b"edited-video")
        return True, "Track-Metadaten wurden aktualisiert."

    monkeypatch.setattr(
        "dragontools.worker.media_stream_metadata_guard.apply_mkv_track_metadata",
        fake_apply,
    )

    tools = SimpleNamespace(ffprobe="ffprobe", mkvpropedit="mkvpropedit")
    ok, message = edit_queued_track(issue, tools=tools, language="de")

    assert ok
    assert video.read_bytes() == b"edited-video"
    assert "<language>deu</language>" in nfo.read_text(encoding="utf-8")
    assert "NFO-Sprachtag" in message


def test_malformed_existing_nfo_blocks_video_language_commit(monkeypatch, tmp_path: Path) -> None:
    video = tmp_path / "Episode.mkv"
    video.write_bytes(b"original-video")
    nfo = tmp_path / "Episode.nfo"
    nfo.write_text("<episodedetails><fileinfo>", encoding="utf-8")
    issue = _issue(video, nfo)

    monkeypatch.setattr(
        "dragontools.worker.media_stream_metadata_guard._validate_track",
        lambda *_args, **_kwargs: None,
    )

    def fake_apply(staged_path: str, **_kwargs):
        Path(staged_path).write_bytes(b"edited-video")
        return True, "Track-Metadaten wurden aktualisiert."

    monkeypatch.setattr(
        "dragontools.worker.media_stream_metadata_guard.apply_mkv_track_metadata",
        fake_apply,
    )

    tools = SimpleNamespace(ffprobe="ffprobe", mkvpropedit="mkvpropedit")
    ok, message = edit_queued_track(issue, tools=tools, language="de")

    assert not ok
    assert video.read_bytes() == b"original-video"
    assert "NFO" in message


def test_stream_fix_discovery_carries_known_nfo_path(tmp_path: Path) -> None:
    db = initialize_database(tmp_path / "library.sqlite3")
    video = tmp_path / "Movie.mkv"
    video.write_bytes(b"mkv")
    nfo = tmp_path / "Movie.nfo"
    _nfo(nfo, audio_languages=("und",))
    with closing(_connect(db)) as conn, conn:
        cursor = conn.execute(
            """
            INSERT INTO media_items(item_type,title,path,filename,duration_s,width,height,video_codec,
                nfo_status,nfo_path,trickplay_status,analysis_status,exists_flag,active,created_at,updated_at)
            VALUES('movie','Movie',?,'Movie.mkv',1200,1920,1080,'hevc','present',?,'present','ok',1,1,'now','now')
            """,
            (str(video), str(nfo)),
        )
        conn.execute(
            "INSERT INTO media_streams(media_id,stream_type,stream_index,codec,language,channels,bitrate,title) "
            "VALUES(?, 'Audio', 1, 'eac3', 'und', 6, 640000, '')",
            (int(cursor.lastrowid),),
        )

    result = discover_fix_issues(db, categories={"streams"})
    assert len(result.issues) == 1
    assert result.issues[0].nfo_path == str(nfo)


def test_local_whisper_model_directory_overrides_model_name(tmp_path: Path) -> None:
    model = tmp_path / "whisper-small"
    model.mkdir()
    (model / "model.bin").write_bytes(b"x")
    (model / "config.json").write_text("{}", encoding="utf-8")

    ok, detail = validate_local_whisper_model_dir(model)
    assert ok
    assert "Lokales CTranslate2-Modell" in detail
    assert resolve_whisper_model_reference(model_name="large-v3", model_dir=model) == str(model)


def test_invalid_configured_local_whisper_model_is_rejected(tmp_path: Path) -> None:
    model = tmp_path / "broken-model"
    model.mkdir()
    (model / "config.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="model.bin"):
        resolve_whisper_model_reference(model_name="small", model_dir=model)


def test_whisper_diagnostic_reports_invalid_local_model_even_when_package_state_varies(tmp_path: Path) -> None:
    from dragontools.core.tool_diagnostics import format_tool_diagnostics

    model = tmp_path / "broken-model"
    model.mkdir()
    row = build_whisper_diagnostic(model)
    assert row["name"] == "faster-whisper"
    assert "model.bin" in row["error"]
    assert not row["found"]
    assert "model.bin" in format_tool_diagnostics([row])


def test_tool_settings_expose_live_check_and_local_whisper_model() -> None:
    root = Path(__file__).resolve().parents[1]
    runtime = (root / "gui" / "settings_sections" / "runtime.py").read_text(encoding="utf-8")
    live = (root / "gui" / "tool_path_live_check.py").read_text(encoding="utf-8")
    main = (root / "gui" / "main_window_system_actions.py").read_text(encoding="utf-8")

    assert "Eingaben prüfen" in runtime
    assert "check_current_tools" in runtime
    assert "whisper_model_dir_edit" in runtime
    assert "provider = _CurrentToolPathProvider(values)" in live
    assert "build_whisper_diagnostic" in live
    assert "build_whisper_diagnostic" in main


def test_media_library_stream_rows_keep_real_container_indexes() -> None:
    from dragontools.core.media_library_media_info_mapper import _streams_from_media_info

    info = SimpleNamespace(
        video_streams=[SimpleNamespace(
            index=0, codec="hevc", bitrate=1, width=1920, height=1080,
            hdr_format=None, pix_fmt="yuv420p", bit_depth=8, profile="Main",
            duration_s=10.0, frame_count=240, frame_rate="24/1", frame_rate_mode="CFR",
            color_space="bt709", color_transfer="bt709", color_primaries="bt709",
        )],
        audio_streams=[SimpleNamespace(
            index=2, codec="eac3", language="und", channels=6, channel_layout="5.1",
            bitrate=640000, title="Audio",
        )],
        subtitle_streams=[SimpleNamespace(
            index=5, codec="subrip", language="deu", forced=False, duration_s=10.0,
            source_kind="internal", external_path=None, title="Deutsch",
        )],
        dolby_vision_profile=None,
    )

    streams = _streams_from_media_info(info)
    assert [row["stream_index"] for row in streams] == [0, 2, 5]


def test_whisper_local_model_mode_can_be_explicitly_enabled_or_disabled(tmp_path: Path) -> None:
    model = tmp_path / "whisper-small"
    model.mkdir()
    (model / "model.bin").write_bytes(b"x")
    (model / "config.json").write_text("{}", encoding="utf-8")

    assert resolve_whisper_model_reference(
        model_name="small",
        model_dir=model,
        use_local_model=True,
    ) == str(model)
    assert resolve_whisper_model_reference(
        model_name="small",
        model_dir=model,
        use_local_model=False,
    ) == "small"

    with pytest.raises(RuntimeError, match="kein Modellordner"):
        resolve_whisper_model_reference(
            model_name="small",
            model_dir="",
            use_local_model=True,
        )


def test_tool_settings_layout_and_diagnostics_are_compact_and_scrollable() -> None:
    root = Path(__file__).resolve().parents[1]
    runtime = (root / "gui" / "settings_sections" / "runtime.py").read_text(encoding="utf-8")
    dialog = (root / "gui" / "tool_diagnostics_dialog.py").read_text(encoding="utf-8")
    worker = (root / "worker" / "media_stream_language_service.py").read_text(encoding="utf-8")

    assert 'tg.addWidget(top_bar, 0, 0, 1, 5)' in runtime
    assert 'whisper_local_model_cb = QCheckBox' in runtime
    assert 'SET_KEY_WHISPER_USE_LOCAL_MODEL' in runtime
    assert 'whisper_use_local_model=d.whisper_local_model_cb.isChecked()' in runtime
    assert 'QPlainTextEdit' in dialog
    assert 'LineWrapMode.WidgetWidth' in dialog
    assert 'SET_KEY_WHISPER_USE_LOCAL_MODEL' in worker
    assert 'use_local_model=self.use_local_model' in worker
