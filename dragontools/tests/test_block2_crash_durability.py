from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _run_child(code: str, *, project_root: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root)
    return subprocess.run(
        [sys.executable, "-c", code],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def test_move_hard_crash_after_backup_rename_is_recovered(tmp_path):
    project_root = Path(__file__).resolve().parents[2]
    source = tmp_path / "source.mkv"
    target_dir = tmp_path / "target"
    target = target_dir / source.name
    target_dir.mkdir()
    source.write_bytes(b"NEW")
    target.write_bytes(b"OLD")

    code = f'''
import os
from pathlib import Path
from dragontools.core.move_file_service import MoveFileService
from dragontools.core.move_journal import MoveJournal
from dragontools.core import move_file_service as mfs
root = Path({str(tmp_path)!r})
source = Path({str(source)!r})
target_dir = Path({str(target_dir)!r})
journal = MoveJournal.start(files=[str(source)], conflict_mode="overwrite", root=root)
journal.start_file(str(source), target_dir=str(target_dir), dest_path=str(target_dir / source.name))
real_replace = os.replace
def crash_after_backup(src, dst):
    real_replace(src, dst)
    if ".__dragontools_backup__" in str(dst):
        os._exit(77)
mfs.os.replace = crash_after_backup
svc = MoveFileService(conflict_mode="overwrite", log=lambda *_: None, wait=lambda: None, abort_immediately=lambda: False, journal=journal)
svc.move(source, target_dir)
'''
    proc = _run_child(code, project_root=project_root)
    assert proc.returncode == 77, proc.stderr
    assert not target.exists()
    backups = list(target_dir.glob(f"{target.name}.__dragontools_backup__*"))
    assert len(backups) == 1

    from dragontools.core.move_journal import recover_active_move_backups

    result = recover_active_move_backups(tmp_path)
    assert result["restored"] == 1
    assert target.read_bytes() == b"OLD"
    assert source.read_bytes() == b"NEW"
    assert not backups[0].exists()


def test_replace_hard_crash_after_original_backup_is_recovered(tmp_path):
    project_root = Path(__file__).resolve().parents[2]
    source = tmp_path / "movie.mkv"
    staging = tmp_path / "movie.__new__.mkv"
    source.write_bytes(b"O" * 4096)
    staging.write_bytes(b"N" * 4096)

    code = f'''
import os
from pathlib import Path
from dragontools.worker.replace_service import ReplaceService
from dragontools.core import move_transaction as mt
source = Path({str(source)!r})
staging = Path({str(staging)!r})
real_replace = os.replace
def crash_after_backup(src, dst):
    real_replace(src, dst)
    if ".dragontools_backup" in str(dst):
        os._exit(78)
mt.os.replace = crash_after_backup
svc = ReplaceService(overwrite_original=True, log=lambda *_: None, journal_root=Path({str(tmp_path)!r}))
svc.replace(input_path=str(source), output_path=str(staging), container="mkv")
'''
    proc = _run_child(code, project_root=project_root)
    assert proc.returncode == 78, proc.stderr
    assert not source.exists()
    assert staging.exists()
    assert list(tmp_path.glob("movie.mkv.dragontools_backup*"))

    from dragontools.core.replace_journal import recover_active_replace_journals

    result = recover_active_replace_journals(tmp_path)
    assert result["restored"] == 1
    assert source.read_bytes() == b"O" * 4096
    assert staging.read_bytes() == b"N" * 4096
    assert not list(tmp_path.glob("movie.mkv.dragontools_backup*"))


def test_replace_container_change_cleanup_pending_is_retried_on_recovery(tmp_path, monkeypatch):
    from dragontools.core.replace_journal import list_replace_journals, recover_active_replace_journals
    from dragontools.worker import replace_service as module
    from dragontools.worker.replace_service import ReplaceService

    source = tmp_path / "movie.mkv"
    staging = tmp_path / "movie.__new__.mp4"
    source.write_bytes(b"O" * 4096)
    staging.write_bytes(b"N" * 4096)

    real_remove = module.os.remove
    monkeypatch.setattr(module.os, "remove", lambda _p: (_ for _ in ()).throw(PermissionError("locked")))
    svc = ReplaceService(overwrite_original=True, log=lambda *_: None, journal_root=tmp_path)
    final = svc.replace(input_path=str(source), output_path=str(staging), container="mp4")
    monkeypatch.setattr(module.os, "remove", real_remove)

    assert Path(final).exists()
    assert source.exists()
    assert svc.cleanup_pending(str(source)) is True
    assert len(list_replace_journals(tmp_path)) == 1

    result = recover_active_replace_journals(tmp_path)
    assert result["cleaned_sources"] == 1
    assert not source.exists()
    assert Path(final).exists()
    assert not list_replace_journals(tmp_path)


def test_move_cleanup_pending_is_recovered_and_status_becomes_ok(tmp_path):
    from dragontools.core.move_journal import MoveJournal, read_move_journal_path, recover_active_move_backups

    source = tmp_path / "source.mkv"
    dest = tmp_path / "dest.mkv"
    source.write_bytes(b"same")
    dest.write_bytes(b"same")
    journal = MoveJournal.start(files=[str(source)], root=tmp_path)
    journal.start_file(str(source), target_dir=str(tmp_path), dest_path=str(dest))
    journal.set_cleanup_pending(str(source), message="Quelle gesperrt")
    journal.finish_file(str(source), status="warn", dest_path=str(dest), message="Quelle gesperrt")

    result = recover_active_move_backups(tmp_path)
    assert result["cleaned"] >= 1
    assert not source.exists()
    data = read_move_journal_path(journal.path)
    # Nach erfolgreichem Cleanup ist der Run terminal und darf bereits archiviert sein.
    if data is not None:
        row = data["files"][str(source)]
        assert row["status"] == "ok"
        assert row["cleanup_pending"] is False


def test_replace_journal_failure_aborts_before_original_is_renamed(tmp_path, monkeypatch):
    from dragontools.core import replace_journal as journal_module
    from dragontools.core.replace_journal import ReplaceJournalWriteError
    from dragontools.worker.replace_service import ReplaceService

    source = tmp_path / "movie.mkv"
    staging = tmp_path / "movie.__new__.mkv"
    source.write_bytes(b"O" * 4096)
    staging.write_bytes(b"N" * 4096)

    monkeypatch.setattr(journal_module, "atomic_write_json", lambda *_a, **_k: (_ for _ in ()).throw(OSError("disk full")))
    svc = ReplaceService(overwrite_original=True, log=lambda *_: None, journal_root=tmp_path)

    with pytest.raises(ReplaceJournalWriteError, match="disk full"):
        svc.replace(input_path=str(source), output_path=str(staging), container="mkv")

    assert source.read_bytes() == b"O" * 4096
    assert staging.read_bytes() == b"N" * 4096
    assert not list(tmp_path.glob("movie.mkv.dragontools_backup*"))
