from __future__ import annotations

import threading
import errno
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_same_path_commit_journal_failure_restores_original_and_staging(tmp_path: Path, monkeypatch) -> None:
    """A post-install journal failure must not leave a failed commit visible."""
    import dragontools.core.output_replace as module
    from dragontools.core.replace_journal import ReplaceJournalWriteError

    source = tmp_path / "movie.mkv"
    staging = tmp_path / "movie.__new__.mkv"
    source.write_bytes(b"OLD")
    staging.write_bytes(b"NEW")

    real_set_status = module.ReplaceJournal.set_status

    def fail_committed(self, status: str, **kwargs):
        if status == "committed":
            raise ReplaceJournalWriteError("simulated journal write failure")
        return real_set_status(self, status, **kwargs)

    monkeypatch.setattr(module.ReplaceJournal, "set_status", fail_committed)

    with pytest.raises(ReplaceJournalWriteError, match="journal write failure"):
        module.commit_staged_output(
            source=source,
            staging=staging,
            destination=source,
            log=lambda *_args: None,
            journal_root=tmp_path / "journals",
        )

    assert source.read_bytes() == b"OLD"
    assert staging.read_bytes() == b"NEW"
    assert not list(tmp_path.glob("movie.mkv.dragontools_backup*"))


@pytest.mark.parametrize("existing_target", [False, True])
def test_backup_export_is_atomic_on_write_failure(
    tmp_path: Path, monkeypatch, existing_target: bool
) -> None:
    """Failed export must not publish a partial ZIP or destroy a valid old backup."""
    import dragontools.core.settings_backup_export as module

    class Settings:
        def allKeys(self):
            return ["normal/key"]

        def value(self, key):
            return "value"

    target = tmp_path / "backup.zip"
    old = b"KNOWN-GOOD-BACKUP"
    if existing_target:
        target.write_bytes(old)

    real_zip = module.zipfile.ZipFile

    class FailingZip(real_zip):
        def writestr(self, *args, **kwargs):
            super().writestr(*args, **kwargs)
            raise OSError("disk full")

    monkeypatch.setattr(module.zipfile, "ZipFile", FailingZip)

    with pytest.raises(OSError, match="disk full"):
        module.export_backup(target, settings=Settings(), documents_dir=tmp_path / "docs")

    if existing_target:
        assert target.read_bytes() == old
    else:
        assert not target.exists()


def test_large_destructive_move_verification_detects_corruption_outside_samples(tmp_path: Path) -> None:
    """Equal-size corruption anywhere in a destructive copy must block source deletion."""
    from dragontools.core.move_copy_verification import _SAMPLE_BYTES, verify_staged_file_copy

    source = tmp_path / "source.bin"
    staged = tmp_path / "staged.bin"
    size = _SAMPLE_BYTES * 6
    source.write_bytes(b"A" * size)
    staged.write_bytes(b"A" * size)

    # Deliberately outside current first/middle/last sampling windows.
    with staged.open("r+b") as handle:
        handle.seek(_SAMPLE_BYTES + (_SAMPLE_BYTES // 4))
        handle.write(b"Z")

    with pytest.raises(OSError, match="Integritätsprüfung"):
        verify_staged_file_copy(source, staged)


def test_converter_executor_terminate_targets_requested_process(monkeypatch) -> None:
    """A cancellation helper must never terminate another job's current process slot."""
    import dragontools.worker.converter_process_executor as module

    requested_process = object()
    other_job_process = object()
    calls: list[dict] = []
    worker = SimpleNamespace(
        _lock=threading.Lock(),
        _current_process=other_job_process,
        log=lambda *_args, **_kwargs: None,
    )

    monkeypatch.setattr(
        module,
        "terminate_process_tree",
        lambda *_args, **kwargs: calls.append(kwargs),
    )

    module.ConverterProcessExecutor(worker).terminate(requested_process, label="review")

    assert calls and calls[0].get("process") is requested_process


def test_cross_volume_directory_move_failure_removes_partial_destination(tmp_path: Path, monkeypatch) -> None:
    """A failed directory transfer must not leave a destination that looks committed."""
    import dragontools.core.move_transfer_executor as module

    source = tmp_path / "source_dir"
    destination = tmp_path / "target_dir"
    source.mkdir()
    (source / "one.bin").write_bytes(b"one")
    (source / "two.bin").write_bytes(b"two")

    class Journal:
        def set_destination(self, *_args, **_kwargs):
            return None

    class Conflicts:
        def unique_backup_path(self, path):
            return path.with_name(path.name + '.backup')

        def rollback(self, *_args, **_kwargs):
            return None

    def partial_then_fail(src: str, dst: str):
        target = Path(dst)
        target.mkdir(parents=True)
        (target / "one.bin").write_bytes(b"one")
        raise OSError("simulated cross-volume copy failure")

    # The implementation now stages instead of calling shutil.move. Inject
    # the same partial-copy failure at that new boundary, forcing EXDEV first.
    import dragontools.core.move_transaction as transaction_module

    def cross_volume(*_args):
        raise OSError(errno.EXDEV, 'different volumes')

    monkeypatch.setattr(module.os, "rename", cross_volume)
    monkeypatch.setattr(transaction_module, "copy_path_to_staging", partial_then_fail)
    executor = module.MoveTransferExecutor(
        log=lambda *_args: None,
        wait=lambda: None,
        abort_immediately=lambda: False,
        journal=Journal(),
        conflicts=Conflicts(),
    )
    result: dict = {}

    ok = executor.move_directory(source, destination, result, conflict_mode="skip")

    assert ok is False
    assert source.is_dir()
    assert sorted(path.name for path in source.iterdir()) == ["one.bin", "two.bin"]
    assert not destination.exists()
    assert not list(tmp_path.glob('*.__dragontools_partial__*'))
