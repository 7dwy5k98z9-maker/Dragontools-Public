from __future__ import annotations

from pathlib import Path

import pytest


def test_move_journal_keeps_failed_files_for_restart(tmp_path):
    from dragontools.core.move_journal import (
        MoveJournal,
        build_move_resume_plan,
        read_active_move_journal,
    )

    ok_file = str(tmp_path / "ok.mkv")
    failed_file = str(tmp_path / "failed.mkv")
    journal = MoveJournal.start(
        files=[ok_file, failed_file],
        target_paths={"tv": str(tmp_path / "TV")},
        conflict_mode="overwrite",
        root=tmp_path,
    )
    journal.start_file(ok_file, target_dir=str(tmp_path / "TV"))
    journal.finish_file(ok_file, status="ok", dest_path=str(tmp_path / "TV" / "ok.mkv"))
    journal.start_file(failed_file, target_dir=str(tmp_path / "TV"))
    journal.finish_file(failed_file, status="error", message="SMB getrennt")
    journal.finish_run(status="incomplete", keep_active=True)

    data = read_active_move_journal(tmp_path)
    assert data is not None
    plan = build_move_resume_plan(data)
    assert plan["files"] == [failed_file]
    assert plan["counts"]["ok"] == 1
    assert plan["counts"]["retry"] == 1


def test_move_journal_archives_completed_run(tmp_path):
    from dragontools.core.move_journal import (
        MoveJournal,
        read_active_move_journal,
    )

    file_path = str(tmp_path / "a.mkv")
    journal = MoveJournal.start(files=[file_path], root=tmp_path)
    journal.start_file(file_path, target_dir=str(tmp_path / "TV"))
    journal.finish_file(file_path, status="ok")
    journal.finish_run(status="completed", keep_active=False)

    assert read_active_move_journal(tmp_path) is None
    assert not journal.path.exists()
    archived = list((tmp_path / "MoveJournal" / "Abgeschlossen").glob("*.json"))
    assert len(archived) == 1


def test_interrupted_backup_is_restored_only_when_new_target_is_missing(tmp_path):
    from dragontools.core.move_journal import recover_interrupted_backups

    original = tmp_path / "Serie - S01E03 - Alt.mkv"
    backup = tmp_path / "Serie - S01E03 - Alt.mkv.__dragontools_backup__123"
    dest = tmp_path / "Serie - S01E03 - Neu.mkv"
    backup.write_bytes(b"old")

    data = {
        "files": {
            str(tmp_path / "source.mkv"): {
                "status": "running",
                "dest_path": str(dest),
                "backup_pairs": [{"original": str(original), "backup": str(backup)}],
            }
        }
    }

    result = recover_interrupted_backups(data)

    assert result["restored"] == 1
    assert result["kept"] == 0
    assert result["failed"] == 0
    assert result["completed"] == 0
    assert original.read_bytes() == b"old"
    assert not backup.exists()
    assert data["files"][str(tmp_path / "source.mkv")]["backup_pairs"] == []


def test_interrupted_backup_is_cleaned_when_new_target_exists(tmp_path):
    from dragontools.core.move_journal import recover_interrupted_backups

    original = tmp_path / "Serie - S01E03 - Alt.mkv"
    backup = tmp_path / "Serie - S01E03 - Alt.mkv.__dragontools_backup__123"
    dest = tmp_path / "Serie - S01E03 - Neu.mkv"
    backup.write_bytes(b"old")
    dest.write_bytes(b"new")

    data = {
        "files": {
            str(tmp_path / "source.mkv"): {
                "status": "running",
                "dest_path": str(dest),
                "backup_pairs": [{"original": str(original), "backup": str(backup)}],
            }
        }
    }

    source = tmp_path / "source.mkv"
    data["files"] = {
        str(source): data["files"][str(source)]
    }

    result = recover_interrupted_backups(data)

    assert result["restored"] == 0
    assert result["cleaned"] == 1
    assert result["failed"] == 0
    assert not backup.exists()
    assert dest.read_bytes() == b"new"
    assert not original.exists()


def test_running_move_is_completed_after_crash_when_target_exists_and_source_is_gone(tmp_path):
    from dragontools.core.move_journal import recover_interrupted_backups

    source = tmp_path / "source.mkv"
    dest = tmp_path / "target.mkv"
    dest.write_bytes(b"new")
    data = {
        "files": {
            str(source): {
                "status": "running",
                "dest_path": str(dest),
                "backup_pairs": [],
            }
        }
    }

    result = recover_interrupted_backups(data)

    assert result["completed"] == 1
    assert data["files"][str(source)]["status"] == "ok"


def test_move_journals_are_unique_and_do_not_supersede_open_runs(tmp_path):
    from dragontools.core.move_journal import (
        MoveJournal,
        archive_active_move_journal,
        read_active_move_journals,
    )

    first = MoveJournal.start(files=[str(tmp_path / "a.mkv")], root=tmp_path)
    second = MoveJournal.start(files=[str(tmp_path / "b.mkv")], root=tmp_path)

    assert first.path != second.path
    assert first.path.exists()
    assert second.path.exists()
    assert len(read_active_move_journals(tmp_path)) == 2

    archive = archive_active_move_journal(
        status="ignored",
        root=tmp_path,
        journal_path=first.path,
    )

    assert archive is not None and archive.exists()
    assert not first.path.exists()
    assert second.path.exists()
    assert len(read_active_move_journals(tmp_path)) == 1


def test_move_resume_plan_preserves_context(tmp_path):
    from dragontools.core.move_journal import MoveJournal, build_move_resume_plan

    source = str(tmp_path / "source.mkv")
    target_dir = str(tmp_path / "TV" / "Serie")
    sidecar = str(tmp_path / "source.nfo")
    journal = MoveJournal.start(
        files=[source],
        target_paths={"tv": str(tmp_path / "TV")},
        planned_targets={source: {"target_dir": target_dir}},
        sidecar_outputs_by_video={source: [sidecar]},
        conflict_mode="overwrite",
        root=tmp_path,
    )
    journal.start_file(source, target_dir=target_dir, dest_path=str(tmp_path / "TV" / "Serie" / "source.mkv"))

    plan = build_move_resume_plan(journal.data | {"_journal_path": str(journal.path)})

    assert plan["files"] == [source]
    assert plan["planned_targets"][source]["target_dir"] == target_dir
    assert plan["sidecar_outputs_by_video"][source] == [sidecar]
    assert plan["target_paths"]["tv"] == str(tmp_path / "TV")
    assert plan["conflict_mode"] == "overwrite"
    assert plan["journal_path"] == str(journal.path)



def test_move_journal_write_failure_is_fatal(tmp_path, monkeypatch):
    from dragontools.core import move_journal as journal_module

    messages: list[str] = []

    def fail_write(_path, _data):
        raise OSError("simulierter Journal-I/O-Fehler")

    monkeypatch.setattr(journal_module, "_atomic_write_json", fail_write)

    with pytest.raises(journal_module.MoveJournalWriteError):
        journal_module.MoveJournal.start(
            files=[str(tmp_path / "source.mkv")],
            root=tmp_path,
            on_write_error=messages.append,
        )

    assert messages
    assert "Move-Journal konnte nicht geschrieben werden" in messages[0]


def test_recovery_can_cleanup_directory_backup_after_committed_directory_move(tmp_path):
    from dragontools.core.move_journal import recover_interrupted_backups

    source = tmp_path / "source_dir"
    dest = tmp_path / "target_dir"
    backup = tmp_path / "target_dir.__dragontools_backup__abc"
    dest.mkdir()
    (dest / "new.txt").write_text("new", encoding="utf-8")
    backup.mkdir()
    (backup / "old.txt").write_text("old", encoding="utf-8")

    data = {
        "files": {
            str(source): {
                "status": "running",
                "dest_path": str(dest),
                "backup_pairs": [{"original": str(dest), "backup": str(backup)}],
            }
        }
    }

    result = recover_interrupted_backups(data)

    assert result["cleaned"] == 1
    assert result["failed"] == 0
    assert dest.is_dir()
    assert (dest / "new.txt").read_text(encoding="utf-8") == "new"
    assert not backup.exists()
    assert data["files"][str(source)]["backup_pairs"] == []


def test_recovery_keeps_backup_when_source_and_destination_both_exist(tmp_path):
    from dragontools.core.move_journal import recover_interrupted_backups

    source = tmp_path / "source.mkv"
    dest = tmp_path / "target.mkv"
    backup = tmp_path / "target.mkv.__dragontools_backup__ambiguous"
    source.write_bytes(b"source-still-present")
    dest.write_bytes(b"new-target")
    backup.write_bytes(b"old-target")
    data = {
        "files": {
            str(source): {
                "status": "running",
                "dest_path": str(dest),
                "backup_pairs": [{"original": str(dest), "backup": str(backup)}],
            }
        }
    }

    result = recover_interrupted_backups(data)
    row = data["files"][str(source)]

    assert result["ambiguous"] == 1
    assert result["kept"] == 1
    assert result["cleaned"] == 0
    assert result["completed"] == 0
    assert source.read_bytes() == b"source-still-present"
    assert dest.read_bytes() == b"new-target"
    assert backup.read_bytes() == b"old-target"
    assert row["status"] == "running"
    assert row["recovery_status"] == "ambiguous_source_and_destination"
    assert "mehrdeutig" in row["message"]
    assert row["backup_pairs"] == [{"original": str(dest), "backup": str(backup)}]


def test_recovery_restores_backup_when_destination_is_missing_and_source_still_exists(tmp_path):
    from dragontools.core.move_journal import recover_interrupted_backups

    source = tmp_path / "source.mkv"
    dest = tmp_path / "target.mkv"
    backup = tmp_path / "target.mkv.__dragontools_backup__restore"
    source.write_bytes(b"source")
    backup.write_bytes(b"old-target")
    data = {
        "files": {
            str(source): {
                "status": "running",
                "dest_path": str(dest),
                "backup_pairs": [{"original": str(dest), "backup": str(backup)}],
            }
        }
    }

    result = recover_interrupted_backups(data)

    assert result["restored"] == 1
    assert result["failed"] == 0
    assert dest.read_bytes() == b"old-target"
    assert source.read_bytes() == b"source"
    assert not backup.exists()
    assert data["files"][str(source)]["backup_pairs"] == []


def test_recovery_keeps_backup_when_restore_fails(tmp_path, monkeypatch):
    from dragontools.core import move_journal as journal_module

    source = tmp_path / "source.mkv"
    dest = tmp_path / "target.mkv"
    backup = tmp_path / "target.mkv.__dragontools_backup__restore_fail"
    source.write_bytes(b"source")
    backup.write_bytes(b"old-target")
    data = {
        "files": {
            str(source): {
                "status": "running",
                "dest_path": str(dest),
                "backup_pairs": [{"original": str(dest), "backup": str(backup)}],
            }
        }
    }

    def fail_replace(_source, _destination):
        raise OSError("simulierter Restorefehler")

    monkeypatch.setattr(journal_module.os, "replace", fail_replace)
    result = journal_module.recover_interrupted_backups(data)

    assert result["restored"] == 0
    assert result["failed"] == 1
    assert backup.read_bytes() == b"old-target"
    assert not dest.exists()
    assert data["files"][str(source)]["backup_pairs"] == [
        {"original": str(dest), "backup": str(backup)}
    ]


def test_recovery_reports_journal_write_failure_without_deleting_active_journal(tmp_path, monkeypatch):
    from dragontools.core import move_journal as journal_module

    source = tmp_path / "source.mkv"
    dest = tmp_path / "target.mkv"
    backup = tmp_path / "target.mkv.__dragontools_backup__journal_fail"
    source.write_bytes(b"source")
    backup.write_bytes(b"old-target")

    journal = journal_module.MoveJournal.start(files=[str(source)], root=tmp_path)
    journal.start_file(str(source), target_dir=str(tmp_path), dest_path=str(dest))
    journal.set_backups(str(source), [{"original": str(dest), "backup": str(backup)}])

    def fail_journal_write(_path, _data):
        raise OSError("simulierter Journalwrite-Fehler")

    monkeypatch.setattr(journal_module, "_atomic_write_json", fail_journal_write)

    result = journal_module.recover_active_move_backups(tmp_path)

    assert result["restored"] == 1
    assert result["failed"] == 1
    assert dest.read_bytes() == b"old-target"
    assert not backup.exists()
    assert journal.path.exists()


def test_move_resume_summary_surfaces_ambiguous_recovery_state(tmp_path):
    from dragontools.core.move_journal import format_unfinished_move_summary

    source = tmp_path / "source.mkv"
    data = {
        "files": {
            str(source): {
                "status": "running",
                "recovery_status": "ambiguous_source_and_destination",
            }
        }
    }

    summary = format_unfinished_move_summary(data)

    assert "Recovery-Hinweis" in summary
    assert "mehrdeutig" in summary


def test_sidecars_pending_is_not_marked_complete_after_video_commit_crash(tmp_path):
    from dragontools.core.move_journal import recover_interrupted_backups

    source = tmp_path / "source.mkv"
    dest = tmp_path / "TV" / "source.mkv"
    dest.parent.mkdir()
    dest.write_bytes(b"video")
    data = {
        "files": {
            str(source): {
                "status": "running",
                "phase": "sidecars_pending",
                "dest_path": str(dest),
                "backup_pairs": [],
            }
        }
    }

    result = recover_interrupted_backups(data)

    assert result["completed"] == 0
    assert data["files"][str(source)]["status"] == "running"
    assert data["files"][str(source)]["phase"] == "sidecars_pending"


def test_resume_plan_uses_committed_video_for_companion_only_recovery(tmp_path):
    from dragontools.core.move_journal import build_move_resume_plan

    source = tmp_path / "work" / "episode.mkv"
    dest = tmp_path / "TV" / "Serie" / "episode.mkv"
    sidecar = tmp_path / "work" / "episode.de.srt"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"video")
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text("sub", encoding="utf-8")
    data = {
        "files": {
            str(source): {
                "status": "warn",
                "phase": "sidecars_pending",
                "target_dir": str(dest.parent),
                "dest_path": str(dest),
            }
        },
        "planned_targets": {str(source): {"target_dir": str(dest.parent)}},
        "sidecar_outputs_by_video": {str(source): [str(sidecar)]},
    }

    plan = build_move_resume_plan(data)

    assert plan["files"] == [str(dest)]
    assert plan["companion_resume_sources"] == {str(dest): str(source)}
    assert plan["sidecar_outputs_by_video"][str(dest)] == [str(sidecar)]
    assert plan["planned_targets"][str(dest)]["target_dir"] == str(dest.parent)
