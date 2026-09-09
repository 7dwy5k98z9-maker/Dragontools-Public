from __future__ import annotations

from pathlib import Path

import pytest

from dragontools.core.move_transaction import (
    PathSwapTransaction,
    PathTransactionRollbackError,
)


def _tree_pair(tmp_path: Path):
    source = tmp_path / "source" / "Season"
    destination = tmp_path / "target" / "Season"
    source.mkdir(parents=True)
    destination.mkdir(parents=True)
    (source / "new.txt").write_text("new", encoding="utf-8")
    (destination / "old.txt").write_text("old", encoding="utf-8")
    backup = destination.with_name(destination.name + ".backup")
    return source, destination, backup


def test_stage_copy_failure_keeps_existing_destination_and_cleans_partial(tmp_path, monkeypatch):
    import dragontools.core.move_transaction as module

    source, destination, backup = _tree_pair(tmp_path)
    tx = PathSwapTransaction(source, destination, backup)

    def failing_copytree(_src, dst, *args, **kwargs):
        partial = Path(dst)
        partial.mkdir(parents=True)
        (partial / "partial.txt").write_text("partial", encoding="utf-8")
        raise OSError("simulierter Copy-Fehler")

    monkeypatch.setattr(module.shutil, "copytree", failing_copytree)

    with pytest.raises(OSError, match="simulierter Copy-Fehler"):
        tx.stage()

    assert source.exists()
    assert (destination / "old.txt").read_text(encoding="utf-8") == "old"
    assert not backup.exists()
    assert tx.staging_path is None or not tx.staging_path.exists()


def test_commit_failure_restores_old_destination(tmp_path, monkeypatch):
    import dragontools.core.move_transaction as module

    source, destination, backup = _tree_pair(tmp_path)
    tx = PathSwapTransaction(source, destination, backup)
    stage = tx.stage()
    real_replace = module.os.replace

    def failing_replace(src, dst):
        if Path(src) == stage and Path(dst) == destination:
            raise OSError("simulierter Commit-Fehler")
        return real_replace(src, dst)

    monkeypatch.setattr(module.os, "replace", failing_replace)

    with pytest.raises(OSError, match="simulierter Commit-Fehler"):
        tx.commit()

    assert source.exists()
    assert destination.exists()
    assert (destination / "old.txt").read_text(encoding="utf-8") == "old"
    assert not backup.exists()


def test_backup_callback_failure_is_rolled_back_and_propagated(tmp_path):
    source, destination, backup = _tree_pair(tmp_path)
    tx = PathSwapTransaction(source, destination, backup)
    tx.stage()

    class JournalFailure(RuntimeError):
        pass

    def fail_journal(_original, _backup):
        raise JournalFailure("Journal nicht schreibbar")

    with pytest.raises(JournalFailure, match="Journal nicht schreibbar"):
        tx.commit(on_backup=fail_journal)

    assert destination.exists()
    assert (destination / "old.txt").read_text(encoding="utf-8") == "old"
    assert not backup.exists()
    assert source.exists()


def test_successful_commit_keeps_backup_until_explicit_discard(tmp_path):
    source, destination, backup = _tree_pair(tmp_path)
    tx = PathSwapTransaction(source, destination, backup)
    tx.stage()
    tx.commit()

    assert tx.committed is True
    assert source.exists(), "Quell-Cleanup ist bewusst Sache des aufrufenden Workflows"
    assert (destination / "new.txt").read_text(encoding="utf-8") == "new"
    assert (backup / "old.txt").read_text(encoding="utf-8") == "old"

    tx.discard_backup()
    assert not backup.exists()


def test_failed_rollback_surfaces_backup_path(tmp_path, monkeypatch):
    import dragontools.core.move_transaction as module

    source, destination, backup = _tree_pair(tmp_path)
    tx = PathSwapTransaction(source, destination, backup)
    stage = tx.stage()
    real_replace = module.os.replace

    def fail_commit_and_rollback(src, dst):
        src_p, dst_p = Path(src), Path(dst)
        if src_p == stage and dst_p == destination:
            raise OSError("commit kaputt")
        if src_p == backup and dst_p == destination:
            raise OSError("rollback kaputt")
        return real_replace(src, dst)

    monkeypatch.setattr(module.os, "replace", fail_commit_and_rollback)

    with pytest.raises(PathTransactionRollbackError) as exc_info:
        tx.commit()

    exc = exc_info.value
    assert exc.backup_path == backup
    assert backup.exists(), "Altbestand muss bei Rollbackfehler unter Backupnamen erhalten bleiben"
    assert not destination.exists()
    assert source.exists()


def test_external_staging_can_survive_commit_failure_for_caller_recovery(tmp_path, monkeypatch):
    import dragontools.core.move_transaction as module

    destination = tmp_path / "film.mkv"
    staging = tmp_path / "encoded.tmp.mkv"
    backup = tmp_path / "film.mkv.backup"
    destination.write_bytes(b"original")
    staging.write_bytes(b"encoded")

    tx = PathSwapTransaction(
        source=staging,
        destination=destination,
        backup_path=backup,
        staging_path=staging,
        preserve_staging_on_rollback=True,
    )
    real_replace = module.os.replace

    def failing_replace(src, dst):
        if Path(src) == staging and Path(dst) == destination:
            raise OSError("simulierter Commit-Fehler")
        return real_replace(src, dst)

    monkeypatch.setattr(module.os, "replace", failing_replace)

    with pytest.raises(OSError, match="simulierter Commit-Fehler"):
        tx.commit()

    assert destination.read_bytes() == b"original"
    assert staging.read_bytes() == b"encoded"
    assert not backup.exists()
