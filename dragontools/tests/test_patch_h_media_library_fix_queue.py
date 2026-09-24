from __future__ import annotations

from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from dragontools.core.media_library_db import _connect, initialize_database
from dragontools.core.media_library_fix_queue import (
    ACTION_GENERATE_NFO,
    ACTION_GENERATE_TRICKPLAY,
    ACTION_REANALYZE,
    MediaLibraryFixIssue,
    dedupe_fix_issues,
    discover_fix_issues,
    refresh_sidecar_statuses,
)
from dragontools.worker.media_library_fix_service import MediaLibraryFixService


def _insert_item(
    db: Path,
    path: Path,
    *,
    nfo_status: str = "present",
    trickplay_status: str = "present",
    duration_s: float | None = 120.0,
    video_codec: str | None = "hevc",
    width: int | None = 1920,
    height: int | None = 1080,
    streams: bool = True,
) -> int:
    with closing(_connect(db)) as conn, conn:
        cursor = conn.execute(
            """
            INSERT INTO media_items(
                item_type, title, path, filename, duration_s, width, height,
                video_codec, nfo_status, trickplay_status, analysis_status,
                exists_flag, active, created_at, updated_at
            ) VALUES('movie', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ok', 1, 1, 'now', 'now')
            """,
            (
                path.stem,
                str(path),
                path.name,
                duration_s,
                width,
                height,
                video_codec,
                nfo_status,
                trickplay_status,
            ),
        )
        media_id = int(cursor.lastrowid)
        if streams:
            conn.execute(
                "INSERT INTO media_streams(media_id, stream_type, stream_index, codec, width, height) "
                "VALUES(?, 'Video', 0, 'hevc', 1920, 1080)",
                (media_id,),
            )
            conn.execute(
                "INSERT INTO media_streams(media_id, stream_type, stream_index, codec, channels, language) "
                "VALUES(?, 'Audio', 1, 'eac3', 6, 'deu')",
                (media_id,),
            )
        return media_id


def _issue(media_id: int, path: Path, action: str) -> MediaLibraryFixIssue:
    return MediaLibraryFixIssue(
        media_id=media_id,
        path=str(path),
        title=path.stem,
        item_type="movie",
        issue_type="test",
        action=action,
        problem="Problem",
        action_label="Fix",
    )


def test_discover_fix_issues_finds_actionable_missing_artifacts_and_metadata(tmp_path: Path) -> None:
    db = initialize_database(tmp_path / "library.sqlite3")
    broken = tmp_path / "Broken.mkv"
    healthy = tmp_path / "Healthy.mkv"
    _insert_item(
        db,
        broken,
        nfo_status="missing",
        trickplay_status="missing",
        duration_s=None,
        video_codec=None,
        width=None,
        height=None,
        streams=False,
    )
    _insert_item(db, healthy)

    result = discover_fix_issues(db)

    assert result.scanned_media == 1
    assert not result.truncated
    assert [item.action for item in result.issues] == [
        ACTION_GENERATE_NFO,
        ACTION_GENERATE_TRICKPLAY,
        ACTION_REANALYZE,
    ]
    assert "Dauer unbekannt" in result.issues[-1].detail
    assert "Videostream fehlt" in result.issues[-1].detail


def test_discover_fix_issues_reports_empty_trickplay_without_false_metadata_fix(tmp_path: Path) -> None:
    db = initialize_database(tmp_path / "library.sqlite3")
    video = tmp_path / "Movie.mkv"
    _insert_item(db, video, trickplay_status="empty")

    result = discover_fix_issues(db)

    assert len(result.issues) == 1
    assert result.issues[0].issue_type == "trickplay_empty"
    assert result.issues[0].action == ACTION_GENERATE_TRICKPLAY


def test_dedupe_fix_issues_uses_media_and_action_key(tmp_path: Path) -> None:
    first = _issue(7, tmp_path / "A.mkv", ACTION_REANALYZE)
    same = _issue(7, tmp_path / "A.mkv", ACTION_REANALYZE)
    second_action = _issue(7, tmp_path / "A.mkv", ACTION_GENERATE_NFO)

    assert dedupe_fix_issues([first, same, second_action]) == [first, second_action]


def test_refresh_sidecar_statuses_updates_only_lightweight_status_fields(tmp_path: Path) -> None:
    db = initialize_database(tmp_path / "library.sqlite3")
    video = tmp_path / "Movie.mkv"
    video.write_bytes(b"video")
    media_id = _insert_item(db, video, nfo_status="missing", trickplay_status="missing")
    video.with_suffix(".nfo").write_text("<movie></movie>", encoding="utf-8")
    sprite = video.with_name(f"{video.stem}.trickplay") / "320-10"
    sprite.mkdir(parents=True)
    (sprite / "1.jpg").write_bytes(b"jpg")

    assert refresh_sidecar_statuses(db, video)

    with closing(_connect(db)) as conn:
        row = conn.execute(
            "SELECT nfo_status, trickplay_status, duration_s FROM media_items WHERE id=?",
            (media_id,),
        ).fetchone()
    assert row["nfo_status"] == "present"
    assert row["trickplay_status"] == "present"
    assert row["duration_s"] == 120.0


def test_fix_service_missing_file_isolated_as_error(tmp_path: Path) -> None:
    service = MediaLibraryFixService(
        db_path=str(tmp_path / "library.sqlite3"),
        settings=SimpleNamespace(),
        tools=SimpleNamespace(),
    )
    issue = _issue(1, tmp_path / "missing.mkv", ACTION_REANALYZE)

    outcome = service.execute(issue)

    assert outcome.status == "error"
    assert "nicht gefunden" in outcome.message


def test_fix_service_reanalysis_delegates_to_existing_media_analysis(tmp_path: Path, monkeypatch) -> None:
    video = tmp_path / "Movie.mkv"
    video.write_bytes(b"video")
    calls = []
    monkeypatch.setattr(
        "dragontools.worker.media_library_fix_service.record_media_file",
        lambda db_path, path, tools=None: calls.append((db_path, path, tools)),
    )
    tools = SimpleNamespace(name="tools")
    service = MediaLibraryFixService(
        db_path=str(tmp_path / "library.sqlite3"),
        settings=SimpleNamespace(),
        tools=tools,
    )
    issue = _issue(1, video, ACTION_REANALYZE)

    outcome = service.execute(issue)

    assert outcome.status == "success"
    assert calls == [(str(tmp_path / "library.sqlite3"), str(video), tools)]


def test_fix_service_nfo_creation_refreshes_library_status(tmp_path: Path, monkeypatch) -> None:
    db = initialize_database(tmp_path / "library.sqlite3")
    video = tmp_path / "Movie.mkv"
    video.write_bytes(b"video")
    media_id = _insert_item(db, video, nfo_status="missing")
    service = MediaLibraryFixService(
        db_path=str(db),
        settings=SimpleNamespace(),
        tools=SimpleNamespace(),
    )

    def _create_nfo_only(*, media_path: str):
        Path(media_path).with_suffix(".nfo").write_text("<movie></movie>", encoding="utf-8")
        return SimpleNamespace(items=[], created_paths=[str(Path(media_path).with_suffix('.nfo'))])

    monkeypatch.setattr(service._postprocess, "create_nfo_only", _create_nfo_only)
    outcome = service.execute(_issue(media_id, video, ACTION_GENERATE_NFO))

    assert outcome.status == "success"
    with closing(_connect(db)) as conn:
        row = conn.execute("SELECT nfo_status FROM media_items WHERE id=?", (media_id,)).fetchone()
    assert row["nfo_status"] == "present"


def test_fix_service_unknown_action_does_not_abort_process(tmp_path: Path) -> None:
    video = tmp_path / "Movie.mkv"
    video.write_bytes(b"video")
    service = MediaLibraryFixService(
        db_path=str(tmp_path / "library.sqlite3"),
        settings=SimpleNamespace(),
        tools=SimpleNamespace(),
    )

    outcome = service.execute(_issue(1, video, "does_not_exist"))

    assert outcome.status == "error"
    assert "Unbekannte Fix-Aktion" in outcome.message


def test_postprocess_fix_helpers_force_create_only_policies(tmp_path: Path, monkeypatch) -> None:
    from dragontools.worker.postprocess_models import NfoSettings, PostProcessConfig, PostProcessRunResult
    from dragontools.worker.postprocess_runner import PostProcessService
    from dragontools.worker.trickplay_models import TrickplaySettings

    video = tmp_path / "Movie.mkv"
    video.write_bytes(b"video")
    configured = PostProcessConfig(
        nfo=NfoSettings(enabled=False, conflict_mode="overwrite"),
        trickplay=TrickplaySettings(enabled=False, only_missing=False, conflict_mode="overwrite", source_mode="source"),
    )
    monkeypatch.setattr(
        "dragontools.worker.postprocess_runner.config_from_settings",
        lambda _settings: configured,
    )
    service = PostProcessService(settings=object(), tools=SimpleNamespace(), log=lambda *_args: None)
    captured = {}

    def _fake_nfo(*, input_path, output_path, cfg):
        captured["nfo"] = cfg
        target = Path(output_path).with_suffix(".nfo")
        target.write_text("nfo", encoding="utf-8")
        return target

    def _fake_trickplay(*, video_input, target_output, settings):
        captured["trickplay"] = settings
        return PostProcessRunResult([str(target_output) + ".trickplay"], [])

    monkeypatch.setattr(service, "_create_nfo", _fake_nfo)
    monkeypatch.setattr(service, "_run_trickplay", _fake_trickplay)

    assert service.create_nfo_only(media_path=str(video)).created_paths
    assert captured["nfo"].enabled is True
    assert captured["nfo"].conflict_mode == "skip"

    assert service.create_trickplay_only(media_path=str(video)).created_paths
    assert captured["trickplay"].enabled is True
    assert captured["trickplay"].only_missing is True
    assert captured["trickplay"].conflict_mode == "skip"
    assert captured["trickplay"].source_mode == "output"


def test_fix_queue_source_integration_keeps_dialog_thin() -> None:
    root = Path(__file__).resolve().parents[1]
    dialog_text = (root / "gui" / "media_library_dialog.py").read_text(encoding="utf-8")
    view_text = (root / "gui" / "media_library_dialog_view.py").read_text(encoding="utf-8")
    contract_text = (root / "gui" / "media_library_dialog_contracts.py").read_text(encoding="utf-8")

    assert "MediaLibraryFixActionsMixin" in dialog_text
    assert '"fix": 4' in dialog_text
    assert '"Fix Queue"' in view_text
    assert "build_fix_tab" in view_text
    assert "run_fix_queue" in contract_text


def test_fix_queue_controller_passes_selected_categories_to_discovery_thread() -> None:
    root = Path(__file__).resolve().parents[1]
    controller_text = (root / "gui" / "media_library_fix_controller.py").read_text(encoding="utf-8")
    tab_text = (root / "gui" / "media_library_fix_tab.py").read_text(encoding="utf-8")

    assert "categories = self._selected_categories()" in controller_text
    assert "categories=categories" in controller_text
    assert 'categories.add("nfo")' in controller_text
    assert 'categories.add("trickplay")' in controller_text
    assert 'categories.add("metadata")' in controller_text
    assert controller_text.count("isChecked()") >= 3
    assert tab_text.count("setChecked(True)") >= 3
