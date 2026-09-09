from __future__ import annotations

import builtins
from pathlib import Path


def _service(log=None):
    from dragontools.core.move_file_service import MoveFileService

    return MoveFileService(
        conflict_mode="skip",
        log=log or (lambda *_args: None),
        wait=lambda: None,
        abort_immediately=lambda: False,
        journal=None,
    )


def _episode_fixture(tmp_path):
    src_dir = tmp_path / "work"
    dst_dir = tmp_path / "Serien" / "Serie 1" / "Staffel 01"
    src_dir.mkdir()
    dst_dir.mkdir(parents=True)
    source = src_dir / "Serie 1 - S01E03 - Neuer Titel.mp4"
    old_video = dst_dir / "Serie 1 - S01E03 - Alter Titel.mkv"
    old_nfo = dst_dir / "Serie 1 - S01E03 - Alter Titel.nfo"
    old_trickplay = dst_dir / "Serie 1 - S01E03 - Alter Titel.trickplay"
    source.write_bytes(b"new")
    old_video.write_bytes(b"old")
    old_nfo.write_text("old-nfo", encoding="utf-8")
    old_trickplay.mkdir()
    (old_trickplay / "0.jpg").write_bytes(b"old-jpg")
    return source, dst_dir, old_video, old_nfo, old_trickplay


def test_episode_replacement_removes_old_video_nfo_and_trickplay_together(tmp_path):
    source, dst_dir, old_video, old_nfo, old_trickplay = _episode_fixture(tmp_path)

    ok, result = _service().move(source, dst_dir)

    assert ok is True
    assert not source.exists()
    assert not old_video.exists()
    assert not old_nfo.exists()
    assert not old_trickplay.exists()
    assert (dst_dir / "Serie 1 - S01E03 - Neuer Titel.mp4").read_bytes() == b"new"
    assert result["deleted_existing_count"] == 1
    assert result["replacement_artifact_count"] == 2
    assert result["replacement_artifacts_removed_count"] == 2
    assert result["replacement_artifacts_by_type"] == {"nfo": 1, "trickplay": 1}
    assert not list(dst_dir.glob("*.__dragontools_backup__*"))


def test_episode_replacement_rolls_back_nfo_and_trickplay_when_video_copy_fails(
    tmp_path, monkeypatch
):
    source, dst_dir, old_video, old_nfo, old_trickplay = _episode_fixture(tmp_path)
    from dragontools.core import move_file_service as module

    monkeypatch.setattr(
        module.os,
        "link",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("no hardlink")),
    )
    real_open = builtins.open

    def failing_open(path, mode="r", *args, **kwargs):
        if Path(path) == source and "rb" in mode:
            raise OSError("simulierter Lesefehler")
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", failing_open)

    ok, result = _service().move(source, dst_dir)

    assert ok is False
    assert source.exists()
    assert old_video.read_bytes() == b"old"
    assert old_nfo.read_text(encoding="utf-8") == "old-nfo"
    assert (old_trickplay / "0.jpg").read_bytes() == b"old-jpg"
    assert not (dst_dir / "Serie 1 - S01E03 - Neuer Titel.mp4").exists()
    assert not list(dst_dir.glob("*.__dragontools_backup__*"))
    assert result["replacement_artifact_count"] == 2


def test_episode_replacement_does_not_touch_other_episode_artifacts(tmp_path):
    source, dst_dir, *_ = _episode_fixture(tmp_path)
    other_nfo = dst_dir / "Serie 1 - S01E04 - Andere Folge.nfo"
    other_tp = dst_dir / "Serie 1 - S01E04 - Andere Folge.trickplay"
    other_nfo.write_text("keep", encoding="utf-8")
    other_tp.mkdir()
    (other_tp / "0.jpg").write_bytes(b"keep")

    ok, _result = _service().move(source, dst_dir)

    assert ok is True
    assert other_nfo.read_text(encoding="utf-8") == "keep"
    assert (other_tp / "0.jpg").read_bytes() == b"keep"
