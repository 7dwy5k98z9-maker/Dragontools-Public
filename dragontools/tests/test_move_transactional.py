from __future__ import annotations

import builtins
import threading
from pathlib import Path

import pytest

pytest.importorskip("PyQt6")


def _bare_move_thread():
    from dragontools.worker.move_thread import MoveThread

    thread = MoveThread.__new__(MoveThread)
    thread._move_journal = None
    thread.conflict_mode = "skip"
    thread.abort_requested = False
    thread.abort_type = None
    thread._paused = False
    thread._pause_ev = threading.Event()
    thread._pause_ev.set()
    thread._log = lambda *_args, **_kwargs: None
    return thread


def _trickplay_service(mode: str):
    from dragontools.core.move_file_service import MoveFileService
    from dragontools.core.move_sidecars import MoveSidecarService

    file_service = MoveFileService(
        conflict_mode="skip",
        log=lambda *_args: None,
        wait=lambda: None,
        abort_immediately=lambda: False,
        journal=None,
    )
    return MoveSidecarService(
        filme_path="",
        trickplay_conflict_mode=mode,
        nfo_movie_target_name="movie.nfo",
        move_file=file_service.move,
        log=lambda *_args: None,
        append_report=lambda *_args: None,
        set_last_result=lambda _result: None,
    )


def test_episode_replacement_rolls_back_old_file_when_copy_fails(tmp_path, monkeypatch):
    from dragontools.core import move_file_service as move_file_module

    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target" / "Staffel 01"
    source_dir.mkdir()
    target_dir.mkdir(parents=True)

    source = source_dir / "Serie - S01E03 - Neu.mp4"
    old_target = target_dir / "Serie - S01E03 - Alt.mkv"
    source.write_bytes(b"new-data")
    old_target.write_bytes(b"old-data")

    thread = _bare_move_thread()
    monkeypatch.setattr(move_file_module.os, "link", lambda *_a, **_k: (_ for _ in ()).throw(OSError("no hardlink")))

    real_open = builtins.open

    def failing_open(path, mode="r", *args, **kwargs):
        if Path(path) == source and "rb" in mode:
            raise OSError("simulierter Lesefehler")
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", failing_open)

    ok = thread._move(str(source), str(target_dir))

    assert ok is False
    assert old_target.exists()
    assert old_target.read_bytes() == b"old-data"
    assert source.exists()
    assert not (target_dir / source.name).exists()
    assert not list(target_dir.glob("*.__dragontools_backup__*"))


def test_journal_failure_after_backup_rename_rolls_back_and_propagates(tmp_path):
    from dragontools.core.move_journal import MoveJournalWriteError

    source = tmp_path / "source.mkv"
    old_target = tmp_path / "target.mkv"
    source.write_bytes(b"new")
    old_target.write_bytes(b"old")

    class FailingJournal:
        def __init__(self):
            self.data = {"files": {str(source): {}}}

        def set_backups(self, _source, _pairs):
            raise MoveJournalWriteError("simulierter Journalfehler")

        def clear_backups(self, _source):
            raise MoveJournalWriteError("simulierter Journalfehler")

    from dragontools.core.move_file_service import MoveFileService, new_move_result

    service = MoveFileService(
        conflict_mode="skip",
        log=lambda *_args: None,
        wait=lambda: None,
        abort_immediately=lambda: False,
        journal=FailingJournal(),
    )
    result = new_move_result(str(source), str(tmp_path))

    with pytest.raises(MoveJournalWriteError):
        service.backup_conflicts_transactional(source, [old_target], result)

    assert old_target.exists()
    assert old_target.read_bytes() == b"old"
    assert source.exists()
    assert not list(tmp_path.glob("*.__dragontools_backup__*"))


def test_directory_overwrite_copy_failure_keeps_old_destination(tmp_path, monkeypatch):
    from dragontools.core import move_file_service as move_file_module

    source_parent = tmp_path / "source"
    target_parent = tmp_path / "target"
    source = source_parent / "Season"
    destination = target_parent / "Season"
    source.mkdir(parents=True)
    destination.mkdir(parents=True)
    (source / "new.txt").write_text("new", encoding="utf-8")
    (destination / "old.txt").write_text("old", encoding="utf-8")

    thread = _bare_move_thread()
    thread.conflict_mode = "overwrite"

    def failing_copytree(_src, dst, *args, **kwargs):
        partial = Path(dst)
        partial.mkdir(parents=True)
        (partial / "partial.txt").write_text("partial", encoding="utf-8")
        raise OSError("simulierter Copy-Fehler")

    monkeypatch.setattr(move_file_module.shutil, "copytree", failing_copytree)

    ok = thread._move(str(source), str(target_parent))

    assert ok is False
    assert source.is_dir()
    assert (source / "new.txt").read_text(encoding="utf-8") == "new"
    assert destination.is_dir()
    assert (destination / "old.txt").read_text(encoding="utf-8") == "old"
    assert not list(target_parent.glob("*.__dragontools_backup__*"))
    assert not list(target_parent.glob("*.__dragontools_partial__*"))


def test_directory_overwrite_commit_failure_restores_old_destination(tmp_path, monkeypatch):
    from dragontools.worker import move_thread as move_module

    source_parent = tmp_path / "source"
    target_parent = tmp_path / "target"
    source = source_parent / "Season"
    destination = target_parent / "Season"
    source.mkdir(parents=True)
    destination.mkdir(parents=True)
    (source / "new.txt").write_text("new", encoding="utf-8")
    (destination / "old.txt").write_text("old", encoding="utf-8")

    thread = _bare_move_thread()
    thread.conflict_mode = "overwrite"
    real_replace = move_module.os.replace

    def failing_commit(src, dst):
        if ".__dragontools_partial__" in Path(src).name and Path(dst) == destination:
            raise OSError("simulierter Commit-Fehler")
        return real_replace(src, dst)

    monkeypatch.setattr(move_module.os, "replace", failing_commit)

    ok = thread._move(str(source), str(target_parent))

    assert ok is False
    assert source.is_dir()
    assert (source / "new.txt").read_text(encoding="utf-8") == "new"
    assert destination.is_dir()
    assert (destination / "old.txt").read_text(encoding="utf-8") == "old"
    assert not list(target_parent.glob("*.__dragontools_backup__*"))
    assert not list(target_parent.glob("*.__dragontools_partial__*"))


def test_directory_overwrite_success_commits_new_and_removes_backup(tmp_path):
    source_parent = tmp_path / "source"
    target_parent = tmp_path / "target"
    source = source_parent / "Season"
    destination = target_parent / "Season"
    source.mkdir(parents=True)
    destination.mkdir(parents=True)
    (source / "new.txt").write_text("new", encoding="utf-8")
    (destination / "old.txt").write_text("old", encoding="utf-8")

    thread = _bare_move_thread()
    thread.conflict_mode = "overwrite"

    ok = thread._move(str(source), str(target_parent))

    assert ok is True
    assert not source.exists()
    assert destination.is_dir()
    assert (destination / "new.txt").read_text(encoding="utf-8") == "new"
    assert not (destination / "old.txt").exists()
    assert not list(target_parent.glob("*.__dragontools_backup__*"))
    assert not list(target_parent.glob("*.__dragontools_partial__*"))


def _make_trickplay_pair(tmp_path):
    source_parent = tmp_path / "source"
    target_parent = tmp_path / "target"
    source = source_parent / "episode.trickplay"
    destination = target_parent / "episode.trickplay"
    source.mkdir(parents=True)
    destination.mkdir(parents=True)
    (source / "0001.jpg").write_bytes(b"new-frame")
    (destination / "0001.jpg").write_bytes(b"old-frame")
    return source, destination


def test_trickplay_overwrite_commit_failure_restores_old_target(tmp_path, monkeypatch):
    from dragontools.worker import move_thread as move_module

    source, destination = _make_trickplay_pair(tmp_path)
    service = _trickplay_service("overwrite")
    real_replace = move_module.os.replace

    def failing_commit(src, dst):
        if ".__dragontools_partial__" in Path(src).name and Path(dst) == destination:
            raise OSError("simulierter Trickplay-Commit-Fehler")
        return real_replace(src, dst)

    monkeypatch.setattr(move_module.os, "replace", failing_commit)

    ok, _result = service.move_trickplay(source, destination)

    assert ok is False
    assert source.is_dir()
    assert (source / "0001.jpg").read_bytes() == b"new-frame"
    assert destination.is_dir()
    assert (destination / "0001.jpg").read_bytes() == b"old-frame"
    assert not list(destination.parent.glob("*.__dragontools_backup__*"))
    assert not list(destination.parent.glob("*.__dragontools_partial__*"))


def test_trickplay_backup_commit_failure_restores_original_name(tmp_path, monkeypatch):
    from dragontools.worker import move_thread as move_module

    source, destination = _make_trickplay_pair(tmp_path)
    service = _trickplay_service("backup")
    real_replace = move_module.os.replace

    def failing_commit(src, dst):
        if ".__dragontools_partial__" in Path(src).name and Path(dst) == destination:
            raise OSError("simulierter Trickplay-Commit-Fehler")
        return real_replace(src, dst)

    monkeypatch.setattr(move_module.os, "replace", failing_commit)

    ok, _result = service.move_trickplay(source, destination)

    assert ok is False
    assert source.is_dir()
    assert destination.is_dir()
    assert (destination / "0001.jpg").read_bytes() == b"old-frame"
    assert not (destination.parent / "episode.trickplay.bak").exists()
    assert not list(destination.parent.glob("*.__dragontools_partial__*"))


def test_trickplay_overwrite_success_replaces_old_transactionally(tmp_path):
    source, destination = _make_trickplay_pair(tmp_path)
    service = _trickplay_service("overwrite")

    ok, _result = service.move_trickplay(source, destination)

    assert ok is True
    assert not source.exists()
    assert destination.is_dir()
    assert (destination / "0001.jpg").read_bytes() == b"new-frame"
    assert not list(destination.parent.glob("*.__dragontools_backup__*"))
    assert not list(destination.parent.glob("*.__dragontools_partial__*"))


def test_trickplay_backup_success_keeps_old_version_as_bak(tmp_path):
    source, destination = _make_trickplay_pair(tmp_path)
    service = _trickplay_service("backup")

    ok, _result = service.move_trickplay(source, destination)

    backup = destination.parent / "episode.trickplay.bak"
    assert ok is True
    assert not source.exists()
    assert (destination / "0001.jpg").read_bytes() == b"new-frame"
    assert backup.is_dir()
    assert (backup / "0001.jpg").read_bytes() == b"old-frame"
    assert not list(destination.parent.glob("*.__dragontools_partial__*"))


def test_directory_overwrite_journal_failure_restores_old_destination(tmp_path):
    from dragontools.core.move_journal import MoveJournalWriteError

    source_parent = tmp_path / "source"
    target_parent = tmp_path / "target"
    source = source_parent / "Season"
    destination = target_parent / "Season"
    source.mkdir(parents=True)
    destination.mkdir(parents=True)
    (source / "new.txt").write_text("new", encoding="utf-8")
    (destination / "old.txt").write_text("old", encoding="utf-8")

    class FailingJournal:
        def __init__(self):
            self.data = {"files": {str(source): {}}}

        def set_destination(self, _source, *, target_dir, dest_path):
            return None

        def set_backups(self, _source, _pairs):
            raise MoveJournalWriteError("simulierter Journalfehler")

        def clear_backups(self, _source):
            raise MoveJournalWriteError("simulierter Journalfehler")

    thread = _bare_move_thread()
    thread.conflict_mode = "overwrite"
    thread._move_journal = FailingJournal()

    with pytest.raises(MoveJournalWriteError, match="simulierter Journalfehler"):
        thread._move(str(source), str(target_parent))

    assert source.is_dir()
    assert (source / "new.txt").read_text(encoding="utf-8") == "new"
    assert destination.is_dir()
    assert (destination / "old.txt").read_text(encoding="utf-8") == "old"
    assert not list(target_parent.glob("*.__dragontools_backup__*"))
    assert not list(target_parent.glob("*.__dragontools_partial__*"))
