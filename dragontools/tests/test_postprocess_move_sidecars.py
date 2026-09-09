from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")


def _make_sidecar_service(*, filme_path: str = "", mode: str = "skip", nfo_name: str = "movie.nfo"):
    from dragontools.core.move_file_service import MoveFileService
    from dragontools.core.move_sidecars import MoveSidecarService

    state: dict[str, object] = {}
    file_service = MoveFileService(
        conflict_mode="skip",
        log=lambda *_args: None,
        wait=lambda: None,
        abort_immediately=lambda: False,
        journal=None,
    )
    service = MoveSidecarService(
        filme_path=filme_path,
        trickplay_conflict_mode=mode,
        nfo_movie_target_name=nfo_name,
        move_file=file_service.move,
        log=lambda *_args: None,
        append_report=lambda *_args: None,
        set_last_result=lambda result: state.__setitem__("last", result),
    )
    return service, state


def test_movie_nfo_sidecar_is_renamed_to_movie_nfo_in_film_target(tmp_path):
    from PyQt6.QtCore import QSettings

    from dragontools.core.settings import APP_NAME, APP_ORG, SET_KEY_NFO_MOVIE_TARGET_NAME

    settings = QSettings(APP_ORG, APP_NAME)
    old_value = settings.value(SET_KEY_NFO_MOVIE_TARGET_NAME, None)
    try:
        settings.setValue(SET_KEY_NFO_MOVIE_TARGET_NAME, "movie.nfo")
        films = tmp_path / "Filme"
        target = films / "A" / "Alarmstufe Rot 2 (1995)"
        nfo = tmp_path / "Alarmstufe Rot 2.nfo"
        nfo.write_text("<movie />", encoding="utf-8")

        service, _state = _make_sidecar_service(filme_path=str(films), nfo_name="movie.nfo")

        assert service.sidecar_dest_name(nfo, str(target)) == "movie.nfo"
    finally:
        if old_value is None:
            settings.remove(SET_KEY_NFO_MOVIE_TARGET_NAME)
        else:
            settings.setValue(SET_KEY_NFO_MOVIE_TARGET_NAME, old_value)


def test_episode_nfo_sidecar_keeps_filename_in_series_target(tmp_path):
    from dragontools.worker.move_thread import MoveThread

    films = tmp_path / "Filme"
    series = tmp_path / "Serien" / "Stargate Atlantis" / "Staffel 01"
    nfo = tmp_path / "Stargate Atlantis - S01E15 - 10.000 Jahre.nfo"

    service, _state = _make_sidecar_service(filme_path=str(films))

    assert service.sidecar_dest_name(nfo, str(series)) == nfo.name


def test_trickplay_sidecar_conflict_can_be_backed_up_on_move(tmp_path):
    from dragontools.worker.move_thread import MoveThread

    src = tmp_path / "work" / "Film.trickplay" / "320 - 10x10"
    dst = tmp_path / "target" / "Film.trickplay" / "320 - 10x10"
    src.mkdir(parents=True)
    dst.mkdir(parents=True)
    (src / "0.jpg").write_bytes(b"new")
    (dst / "0.jpg").write_bytes(b"old")

    logs: list[tuple[str, str]] = []

    class _Log:
        def info(self, msg):
            logs.append(("info", msg))

        def warn(self, msg):
            logs.append(("warn", msg))

        def error(self, msg):
            logs.append(("error", msg))

    service, state = _make_sidecar_service(mode="backup")

    ok, result = service.move_trickplay(src.parent, dst.parent)

    assert ok is True
    assert (tmp_path / "target" / "Film.trickplay" / "320 - 10x10" / "0.jpg").read_bytes() == b"new"
    assert (tmp_path / "target" / "Film.trickplay.bak" / "320 - 10x10" / "0.jpg").read_bytes() == b"old"
    assert result["backed_up_existing"] is True


def test_trickplay_sidecar_conflict_can_keep_existing_target(tmp_path):
    from dragontools.worker.move_thread import MoveThread

    src = tmp_path / "work" / "Film.trickplay" / "320 - 10x10"
    dst = tmp_path / "target" / "Film.trickplay" / "320 - 10x10"
    src.mkdir(parents=True)
    dst.mkdir(parents=True)
    (src / "0.jpg").write_bytes(b"new")
    (dst / "0.jpg").write_bytes(b"old")

    service, state = _make_sidecar_service(mode="skip")

    ok, result = service.move_trickplay(src.parent, dst.parent)

    assert ok is True
    assert not (tmp_path / "work" / "Film.trickplay").exists()
    assert (tmp_path / "target" / "Film.trickplay" / "320 - 10x10" / "0.jpg").read_bytes() == b"old"
    assert result["skipped_conflict"] is True


def test_move_thread_replaces_same_sxxexx_even_when_conflict_mode_skip(tmp_path):
    from dragontools.worker.move_thread import MoveThread

    src_dir = tmp_path / "work"
    dst_dir = tmp_path / "Serien" / "Serie 1" / "Staffel 01"
    src_dir.mkdir()
    dst_dir.mkdir(parents=True)
    src = src_dir / "Serie 1 - S01E03 - Neuer Titel.mp4"
    old = dst_dir / "Serie 1 - S01E03 - Alter Titel.mkv"
    src.write_bytes(b"new")
    old.write_bytes(b"old")
    logs: list[str] = []

    worker = MoveThread.__new__(MoveThread)
    worker._logger = SimpleNamespace(info=logs.append, warn=logs.append, error=logs.append)
    worker.conflict_mode = "skip"
    worker._paused = False
    worker.abort_requested = False
    worker.abort_type = None

    ok = worker._move(str(src), str(dst_dir))

    assert ok is True
    assert not old.exists()
    assert not src.exists()
    assert (dst_dir / src.name).read_bytes() == b"new"
    assert worker._last_move_result["episode_identity_replacement"] is True
    assert worker._last_move_result["replacement_reminder_required"] is True
    assert any("SxxExx-Ersetzung" in line for line in logs)


def test_move_thread_records_replacement_reminder(tmp_path, monkeypatch):
    from dragontools.core import replacement_reminders
    from dragontools.core.move_postprocess import record_replacement_reminder

    reminder_path = tmp_path / "reminders.json"
    monkeypatch.setattr(
        replacement_reminders,
        "default_replacement_reminder_path",
        lambda _root=None: reminder_path,
    )
    logs: list[str] = []
    old_path = tmp_path / "Serie 1 - S01E03 - Alt.mkv"
    new_path = tmp_path / "Serie 1 - S01E03 - Neu.mp4"
    move_result = {
        "replacement_reminder_required": True,
        "episode_identity_series": "Serie 1",
        "episode_identity_season": 1,
        "episode_identity_episode": 3,
        "episode_identity_label": "S01E03",
        "replacement_reason": "Gleiche SxxExx-Kennung im Ziel-Staffelordner",
    }

    record_replacement_reminder(
        move_result, str(new_path), [str(old_path)], log=lambda msg, _level="info": logs.append(msg)
    )

    reminders = replacement_reminders.list_replacement_reminders(reminder_path)
    assert len(reminders) == 1
    assert reminders[0]["old_filenames"] == ["Serie 1 - S01E03 - Alt.mkv"]
    assert reminders[0]["new_filename"] == "Serie 1 - S01E03 - Neu.mp4"
    assert move_result["replacement_reminder_id"].startswith("#")
