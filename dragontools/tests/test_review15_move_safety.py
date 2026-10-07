from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from dragontools.core.move_file_service import MoveFileService
from dragontools.core.move_journal_recovery import recover_interrupted_backups
from dragontools.core.move_sidecars import MoveSidecarService
from dragontools.core.move_transaction import PathSwapTransaction
from dragontools.core.transaction_identity import path_receipt


def _sidecar_service(*, conflict_mode: str = "skip", trickplay_mode: str = "skip") -> MoveSidecarService:
    file_service = MoveFileService(
        conflict_mode=conflict_mode,
        log=lambda *_a: None,
        wait=lambda: None,
        abort_immediately=lambda: False,
        journal=None,
    )
    return MoveSidecarService(
        filme_path="",
        trickplay_conflict_mode=trickplay_mode,
        nfo_movie_target_name="movie.nfo",
        move_file=file_service.move,
        overwrite_file=file_service.move,
        log=lambda *_a: None,
        append_report=lambda *_a, **_k: None,
        set_last_result=lambda *_a: None,
    )


def test_companion_staging_copy_failure_never_exposes_partial_final_file(tmp_path, monkeypatch):
    import dragontools.core.move_sidecars as sidecars_mod

    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    source_dir.mkdir()
    target_dir.mkdir()
    video = source_dir / "Episode.mkv"
    video.write_bytes(b"video")
    subtitle = source_dir / "Episode.de.srt"
    subtitle.write_bytes(b"complete-subtitle")
    final = target_dir / subtitle.name

    import dragontools.core.move_transaction as transaction_mod
    real_copy2 = transaction_mod.shutil.copyfileobj

    def failing_copy2(src, dst, *args, **kwargs):
        dst.write(b"partial")
        raise OSError("simulated interrupted copy")

    monkeypatch.setattr(transaction_mod.shutil, "copyfileobj", failing_copy2)
    result = _sidecar_service().stage_before_video(
        str(video), str(target_dir), [str(subtitle)], dest_video_path=str(target_dir / video.name)
    )

    assert result["ok"] is False
    assert subtitle.read_bytes() == b"complete-subtitle"
    assert not final.exists()
    assert not list(target_dir.glob("*.__dragontools_partial__*"))

    monkeypatch.setattr(transaction_mod.shutil, "copyfileobj", real_copy2)


def test_late_file_collision_is_not_overwritten_by_copy_commit(tmp_path, monkeypatch):
    import dragontools.core.move_transfer_executor as transfer_mod

    source = tmp_path / "source.mkv"
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    source.write_bytes(b"new-video")
    destination = target_dir / source.name

    service = MoveFileService(
        conflict_mode="skip",
        log=lambda *_a: None,
        wait=lambda: None,
        abort_immediately=lambda: False,
        journal=None,
    )

    monkeypatch.setattr(transfer_mod.os, "link", lambda *_a, **_k: (_ for _ in ()).throw(OSError("no fast hardlink")))
    real_verify = transfer_mod.verify_staged_file_copy

    def verify_then_create_late_target(src, staged):
        real_verify(src, staged)
        destination.write_bytes(b"concurrent-owner")

    monkeypatch.setattr(transfer_mod, "verify_staged_file_copy", verify_then_create_late_target)

    ok, result = service.move(str(source), str(target_dir))

    assert ok is False
    assert result["ok"] is False
    assert source.read_bytes() == b"new-video"
    assert destination.read_bytes() == b"concurrent-owner"
    assert not list(target_dir.glob("*.__dragontools_partial__*"))


def test_cross_volume_trickplay_copy_failure_keeps_source_and_no_partial_target(tmp_path, monkeypatch):
    import dragontools.core.move_sidecars as sidecars_mod
    import dragontools.core.move_transaction as tx_mod

    source = tmp_path / "source" / "Episode.trickplay"
    destination = tmp_path / "target" / "Episode.trickplay"
    source.mkdir(parents=True)
    destination.parent.mkdir(parents=True)
    (source / "0001.jpg").write_bytes(b"frame")

    real_rename = sidecars_mod.os.rename

    def exdev_for_initial_move(src, dst):
        if Path(src) == source and Path(dst) == destination:
            raise OSError(errno.EXDEV, "cross-device")
        return real_rename(src, dst)

    monkeypatch.setattr(sidecars_mod.os, "rename", exdev_for_initial_move)

    def failing_copytree(_src, dst, *args, **kwargs):
        partial = Path(dst)
        partial.mkdir(parents=True, exist_ok=True)
        (partial / "partial.jpg").write_bytes(b"partial")
        raise OSError("network copy interrupted")

    monkeypatch.setattr(tx_mod.shutil, "copytree", failing_copytree)

    ok, _result = _sidecar_service(trickplay_mode="overwrite").move_trickplay(source, destination)

    assert ok is False
    assert (source / "0001.jpg").read_bytes() == b"frame"
    assert not destination.exists()
    assert not list(destination.parent.glob("*.__dragontools_partial__*"))


def test_recovery_collapses_hardlink_crash_window(tmp_path):
    source = tmp_path / "source.mkv"
    destination = tmp_path / "target.mkv"
    source.write_bytes(b"same-inode")
    expected = path_receipt(source)
    os.link(source, destination)
    assert source.samefile(destination)

    data = {
        "files": {
            str(source): {
                "status": "running",
                "phase": "video_pending",
                "dest_path": str(destination),
                "backup_pairs": [],
                "cleanup_pending": False,
                "commit_proof": {"source": expected, "destination": expected},
                "message": "",
            }
        },
        "sidecar_outputs_by_video": {},
    }

    result = recover_interrupted_backups(data)
    row = data["files"][str(source)]

    assert result["cleaned"] == 1
    assert not source.exists()
    assert destination.read_bytes() == b"same-inode"
    assert row["status"] == "ok"
    assert row["phase"] == "video_pending" or row["phase"] == "completed"
    assert row.get("recovery_status") is None


def test_modified_staged_companion_is_not_used_to_delete_intact_source(tmp_path):
    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    source_dir.mkdir()
    target_dir.mkdir()
    video = source_dir / "Episode.mkv"
    video.write_bytes(b"video")
    nfo = source_dir / "Episode.nfo"
    nfo.write_bytes(b"good-nfo")

    service = _sidecar_service(conflict_mode="skip")
    staged = service.stage_before_video(
        str(video), str(target_dir), [str(nfo)], dest_video_path=str(target_dir / video.name)
    )
    target_nfo = target_dir / nfo.name
    target_nfo.write_bytes(b"modified-after-staging")

    result = service.move_sidecars(
        str(video),
        str(target_dir),
        [str(nfo)],
        dest_video_path=str(target_dir / video.name),
        staged_paths=staged["staged_paths"],
    )

    assert result["ok"] is False
    assert nfo.read_bytes() == b"good-nfo"
    assert target_nfo.read_bytes() == b"modified-after-staging"


def test_rollback_does_not_delete_staged_companion_modified_by_another_actor(tmp_path):
    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    source_dir.mkdir()
    target_dir.mkdir()
    video = source_dir / "Episode.mkv"
    video.write_bytes(b"video")
    subtitle = source_dir / "Episode.de.srt"
    subtitle.write_bytes(b"original")

    service = _sidecar_service()
    staged = service.stage_before_video(
        str(video), str(target_dir), [str(subtitle)], dest_video_path=str(target_dir / video.name)
    )
    target_subtitle = target_dir / subtitle.name
    target_subtitle.write_bytes(b"externally-modified")

    service.rollback_stage(staged)

    assert subtitle.read_bytes() == b"original"
    assert target_subtitle.read_bytes() == b"externally-modified"


def test_path_swap_no_replace_refuses_late_directory_collision(tmp_path):
    source = tmp_path / "source_dir"
    destination = tmp_path / "target_dir"
    backup = tmp_path / "backup_dir"
    source.mkdir()
    (source / "new.txt").write_text("new", encoding="utf-8")

    tx = PathSwapTransaction(
        source,
        destination,
        backup,
        replace_existing_destination=False,
    )
    stage = tx.stage()
    destination.mkdir()
    (destination / "other.txt").write_text("other", encoding="utf-8")

    with pytest.raises(FileExistsError):
        tx.commit()

    assert source.exists()
    assert (destination / "other.txt").read_text(encoding="utf-8") == "other"
    assert stage.exists()
    assert not backup.exists()


def test_direct_resume_of_hardlink_alias_removes_stale_source_name(tmp_path):
    source = tmp_path / "source.mkv"
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    destination = target_dir / source.name
    source.write_bytes(b"video")
    os.link(source, destination)

    service = MoveFileService(
        conflict_mode="skip",
        log=lambda *_a: None,
        wait=lambda: None,
        abort_immediately=lambda: False,
        journal=None,
    )
    ok, result = service.move(str(source), str(target_dir))

    assert ok is True
    assert result["ok"] is True
    assert not source.exists()
    assert destination.read_bytes() == b"video"


def test_episode_replacement_discovers_old_subtitle_companions(tmp_path):
    from dragontools.core.move_conflicts import (
        find_episode_identity_conflicts,
        find_episode_replacement_artifacts,
    )

    target = tmp_path / "Serie" / "Staffel 01"
    target.mkdir(parents=True)
    old_video = target / "Serie - S01E03 - Alter Titel.mkv"
    old_video.write_bytes(b"old")
    old_sub = target / "Serie - S01E03 - Alter Titel.de.srt"
    old_sub.write_text("alt", encoding="utf-8")
    old_pgs = target / "Serie - S01E03 - Alter Titel.de.forced.sup"
    old_pgs.write_bytes(b"pgs")
    other = target / "Serie - S01E04 - Andere Folge.de.srt"
    other.write_text("other", encoding="utf-8")
    incoming = target / "Serie - S01E03 - Neuer Titel.mkv"

    conflicts = find_episode_identity_conflicts(incoming)
    artifacts = find_episode_replacement_artifacts(incoming, conflicts)
    names = {path.name for path in artifacts}

    assert old_sub.name in names
    assert old_pgs.name in names
    assert other.name not in names


def test_episode_replacement_transaction_removes_old_subtitle_but_protects_new_staged_one(tmp_path):
    source_dir = tmp_path / "source"
    target = tmp_path / "Serie" / "Staffel 01"
    source_dir.mkdir()
    target.mkdir(parents=True)

    new_video = source_dir / "Serie - S01E03 - Neuer Titel.mkv"
    new_video.write_bytes(b"new-video")
    new_sub = source_dir / "Serie - S01E03 - Neuer Titel.de.srt"
    new_sub.write_text("new-sub", encoding="utf-8")
    old_video = target / "Serie - S01E03 - Alter Titel.mkv"
    old_video.write_bytes(b"old-video")
    old_sub = target / "Serie - S01E03 - Alter Titel.de.srt"
    old_sub.write_text("old-sub", encoding="utf-8")

    sidecars = _sidecar_service(conflict_mode="skip")
    file_service = MoveFileService(
        conflict_mode="skip",
        log=lambda *_a: None,
        wait=lambda: None,
        abort_immediately=lambda: False,
        journal=None,
        episode_replacement_mode="auto",
    )
    prepared = file_service.prepare_move(str(new_video), str(target))
    staged = sidecars.stage_before_video(
        str(new_video), str(target), [str(new_sub)], dest_video_path=prepared["dest_path"]
    )
    ok, result = file_service.move(
        str(new_video), str(target), prepared=prepared, protected_paths=staged["protected_paths"]
    )

    assert ok is True
    assert result["replacement_artifacts_by_type"]["subtitle"] == 1
    assert not old_sub.exists()
    assert (target / new_sub.name).read_text(encoding="utf-8") == "new-sub"


def test_staged_companion_cleanup_failure_stays_retryable(tmp_path, monkeypatch):
    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    source_dir.mkdir()
    target_dir.mkdir()
    video = source_dir / "Episode.mkv"
    video.write_bytes(b"video")
    sub = source_dir / "Episode.de.srt"
    sub.write_bytes(b"subtitle")
    service = _sidecar_service(conflict_mode="skip")
    staged = service.stage_before_video(
        str(video), str(target_dir), [str(sub)], dest_video_path=str(target_dir / video.name)
    )

    monkeypatch.setattr(service, "_remove_committed_source", lambda _path: False)
    result = service.move_sidecars(
        str(video), str(target_dir), [str(sub)],
        dest_video_path=str(target_dir / video.name), staged_paths=staged["staged_paths"]
    )

    assert result["ok"] is False
    assert result["failed"] == 1
    assert result["results"][0]["cleanup_pending"] is True
    assert sub.exists()
    assert (target_dir / sub.name).exists()


def test_trickplay_cleanup_failure_is_not_reported_as_completed(tmp_path, monkeypatch):
    source = tmp_path / "source" / "Episode.trickplay"
    destination = tmp_path / "target" / "Episode.trickplay"
    source.mkdir(parents=True)
    destination.mkdir(parents=True)
    (source / "0001.jpg").write_bytes(b"new")
    (destination / "0001.jpg").write_bytes(b"old")

    service = _sidecar_service(trickplay_mode="overwrite")
    monkeypatch.setattr(service, "_remove_committed_source", lambda _path: False)
    ok, result = service.move_trickplay(source, destination)

    assert ok is False
    assert result["ok"] is False
    assert result["cleanup_pending"] is True
    assert source.exists()
    assert (destination / "0001.jpg").read_bytes() == b"new"
