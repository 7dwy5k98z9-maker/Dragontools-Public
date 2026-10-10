from pathlib import Path
import shutil

import pytest

from dragontools.core.move_file_service import MoveFileService


def movie_fixture(tmp_path, *, trickplay=True, mode="overwrite"):
    source_dir = tmp_path / "source"
    target = tmp_path / "library"
    source_dir.mkdir()
    target.mkdir()
    source = source_dir / "Der Hobbit - Die Schlacht der fünf Heere (2014).mkv"
    old = target / source.name
    source.write_bytes(b"new-video")
    old.write_bytes(b"old-video")
    cache = old.with_suffix(".trickplay")
    if trickplay:
        cache.mkdir()
        (cache / "0.jpg").write_bytes(b"old-cache")
    nfo = target / "movie.nfo"
    nfo.write_text("<movie><title>Der Hobbit</title></movie>", encoding="utf-8")
    logs = []
    service = MoveFileService(
        conflict_mode=mode, log=lambda message, level: logs.append((message, level)),
        wait=lambda: None, abort_immediately=lambda: False,
    )
    assert not source.with_suffix(".trickplay").exists()
    return source, target, old, cache, nfo, service, logs


@pytest.mark.parametrize("mode", ["overwrite", "delete_first"])
def test_movie_without_any_trickplay_can_replace_old_video(tmp_path, mode):
    source, target, old, cache, nfo, service, _ = movie_fixture(tmp_path, trickplay=False, mode=mode)
    ok, result = service.move(source, target)
    assert ok, result
    assert old.read_bytes() == b"new-video"
    assert not source.exists() and not cache.exists()
    assert not nfo.exists()
    assert not list(target.glob("*.__dragontools_backup__*"))


@pytest.mark.parametrize("mode", ["overwrite", "delete_first"])
def test_movie_cache_is_secured_before_watcher_observes_video_removal(tmp_path, monkeypatch, mode):
    from dragontools.core import move_conflict_transactions as module
    source, target, old, cache, nfo, service, _ = movie_fixture(tmp_path, mode=mode)
    original_publish = module.publish_staged_no_replace

    def publish_then_media_server_cleanup(src, dst):
        original_publish(src, dst)
        if Path(src) == old and ".__dragontools_backup__" in Path(dst).name:
            # A media server can delete derived caches as soon as its video disappears.
            if cache.exists():
                shutil.rmtree(cache)

    monkeypatch.setattr(module, "publish_staged_no_replace", publish_then_media_server_cleanup)
    ok, result = service.move(source, target)
    assert ok, result
    assert old.read_bytes() == b"new-video"
    assert not source.exists() and not cache.exists() and not nfo.exists()
    assert not list(target.glob("*.__dragontools_backup__*"))


def test_movie_trickplay_disappearing_just_before_backup_is_optional(tmp_path, monkeypatch):
    source, target, old, cache, nfo, service, logs = movie_fixture(tmp_path)
    original_backup = service._conflicts.backup

    def remove_cache_then_backup(*args):
        shutil.rmtree(cache)
        return original_backup(*args)

    monkeypatch.setattr(service._conflicts, "backup", remove_cache_then_backup)
    ok, result = service.move(source, target)
    assert ok, result
    assert old.read_bytes() == b"new-video"
    assert not source.exists() and not cache.exists()
    assert result["transaction_backup_count"] == 2  # video and movie.nfo only
    assert any("Trickplay" in message and "übersprungen" in message for message, _ in logs)
    assert not list(target.glob("*.__dragontools_backup__*"))


def test_missing_trickplay_does_not_hide_missing_target_folder(tmp_path, monkeypatch):
    source, target, old, cache, nfo, service, logs = movie_fixture(tmp_path)
    original_backup = service._conflicts.backup

    def remove_target_then_backup(*args):
        shutil.rmtree(target)
        return original_backup(*args)

    monkeypatch.setattr(service._conflicts, "backup", remove_target_then_backup)
    ok, _ = service.move(source, target)
    assert not ok
    assert source.read_bytes() == b"new-video"
    assert any(level == "error" for _, level in logs)


def test_trickplay_permission_error_keeps_old_video_and_source(tmp_path, monkeypatch):
    from dragontools.core import move_conflict_transactions as module
    source, target, old, cache, nfo, service, _ = movie_fixture(tmp_path)
    original_publish = module.publish_staged_no_replace

    def deny_cache_backup(src, dst):
        if Path(src) == cache:
            raise PermissionError("cache locked")
        return original_publish(src, dst)

    monkeypatch.setattr(module, "publish_staged_no_replace", deny_cache_backup)
    ok, _ = service.move(source, target)
    assert not ok
    assert old.read_bytes() == b"old-video" and source.read_bytes() == b"new-video"
    assert (cache / "0.jpg").read_bytes() == b"old-cache"
    assert nfo.exists()
    assert not list(target.glob("*.__dragontools_backup__*"))


def test_video_commit_failure_restores_movie_and_cache(tmp_path, monkeypatch):
    from dragontools.core import move_transfer_executor as module
    source, target, old, cache, nfo, service, _ = movie_fixture(tmp_path)

    def fail_install(*args, **kwargs):
        raise PermissionError("destination locked")

    monkeypatch.setattr(module.os, "link", fail_install)
    monkeypatch.setattr(module, "publish_staged_no_replace", fail_install)
    ok, _ = service.move(source, target)
    assert not ok
    assert old.read_bytes() == b"old-video" and source.read_bytes() == b"new-video"
    assert (cache / "0.jpg").read_bytes() == b"old-cache"
    assert nfo.exists()
    assert not list(target.glob("*.__dragontools_backup__*"))


def test_new_protected_movie_trickplay_is_preserved(tmp_path):
    source, target, old, cache, nfo, service, _ = movie_fixture(tmp_path)
    prepared = service.prepare_move(source, target)
    (cache / "0.jpg").write_bytes(b"new-cache")
    ok, result = service.move(source, target, prepared=prepared, protected_paths=[cache])
    assert ok, result
    assert old.read_bytes() == b"new-video"
    assert (cache / "0.jpg").read_bytes() == b"new-cache"


def test_changed_unprotected_movie_cache_is_not_removed(tmp_path):
    source, target, old, cache, nfo, service, _ = movie_fixture(tmp_path)
    prepared = service.prepare_move(source, target)
    (cache / "0.jpg").write_bytes(b"concurrent-cache")
    ok, result = service.move(source, target, prepared=prepared)
    assert not ok and result["preparation_invalidated"]
    assert old.read_bytes() == b"old-video" and source.exists()
    assert (cache / "0.jpg").read_bytes() == b"concurrent-cache"


def test_trickplay_disappearing_during_rename_clears_pending_journal_pair(tmp_path, monkeypatch):
    from copy import deepcopy
    from dragontools.core import move_conflict_transactions as module
    source, target, old, cache, nfo, service, _ = movie_fixture(tmp_path)
    original_publish = module.publish_staged_no_replace
    recorded_pairs = []
    monkeypatch.setattr(service._journal_ops, "set_backups", lambda _, pairs: recorded_pairs.append(deepcopy(pairs)))

    def remove_cache_before_publish(src, dst):
        if Path(src) == cache:
            shutil.rmtree(cache)
        return original_publish(src, dst)

    monkeypatch.setattr(module, "publish_staged_no_replace", remove_cache_before_publish)
    ok, result = service.move(source, target)
    assert ok, result
    assert old.read_bytes() == b"new-video" and not source.exists()
    assert result["transaction_backup_count"] == 2
    assert recorded_pairs
    assert any(any(pair["original"] == str(cache) for pair in pairs) for pairs in recorded_pairs)
    assert all(pair["original"] != str(cache) for pair in recorded_pairs[-1])
    assert not list(target.glob("*.__dragontools_backup__*"))


def test_missing_child_inside_existing_trickplay_is_not_silently_ignored(tmp_path, monkeypatch):
    from dragontools.core import move_conflict_transactions as module
    source, target, old, cache, nfo, service, logs = movie_fixture(tmp_path)
    original_receipt = module.path_receipt

    def fail_child_read(path):
        if Path(path) == cache:
            raise FileNotFoundError(2, "cache child disappeared", str(cache / "0.jpg"))
        return original_receipt(path)

    monkeypatch.setattr(module, "path_receipt", fail_child_read)
    ok, _ = service.move(source, target)
    assert not ok
    assert old.read_bytes() == b"old-video" and source.read_bytes() == b"new-video"
    assert (cache / "0.jpg").read_bytes() == b"old-cache"
    assert any(level == "error" for _, level in logs)
    assert not list(target.glob("*.__dragontools_backup__*"))


def test_missing_video_conflict_is_not_treated_as_optional(tmp_path, monkeypatch):
    from dragontools.core import move_conflict_transactions as module
    source, target, old, cache, nfo, service, logs = movie_fixture(tmp_path)
    original_publish = module.publish_staged_no_replace

    def remove_old_video_before_publish(src, dst):
        if Path(src) == old:
            old.unlink()
        return original_publish(src, dst)

    monkeypatch.setattr(module, "publish_staged_no_replace", remove_old_video_before_publish)
    ok, _ = service.move(source, target)
    assert not ok and source.read_bytes() == b"new-video"
    assert (cache / "0.jpg").read_bytes() == b"old-cache" and nfo.exists()
    assert any(level == "error" for _, level in logs)
    assert not list(target.glob("*.__dragontools_backup__*"))
