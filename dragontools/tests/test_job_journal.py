from __future__ import annotations

from pathlib import Path


def test_job_journal_records_and_archives_completed_run(tmp_path):
    from dragontools.core.job_journal import JobJournal, active_job_journal_path, read_active_job_journal

    files = [str(tmp_path / "a.mkv"), str(tmp_path / "b.mkv")]
    journal = JobJournal.start(
        files=files,
        codec="h265",
        mode="convert",
        log_file=str(tmp_path / "run.txt"),
        encoder="nvenc",
        root=tmp_path,
    )

    journal.start_file(files[0], index=1, total=2)
    journal.finish_file(files[0], output_path=str(tmp_path / "a_out.mkv"), status="✅")
    journal.finish_run(status="completed")

    assert read_active_job_journal(tmp_path) is None
    assert not active_job_journal_path(tmp_path).exists()

    archived = list((tmp_path / "JobJournal" / "Abgeschlossen").glob("*.json"))
    assert len(archived) == 1
    text = archived[0].read_text(encoding="utf-8")
    assert '"status": "completed"' in text
    assert '"status": "ok"' in text


def test_unfinished_job_summary_uses_active_journal(tmp_path):
    from dragontools.core.job_journal import JobJournal, format_unfinished_job_summary, read_active_job_journal

    file_path = str(tmp_path / "folge.mkv")
    journal = JobJournal.start(
        files=[file_path],
        codec="h265",
        mode="convert",
        root=tmp_path,
    )
    journal.start_file(file_path, index=1, total=1)

    data = read_active_job_journal(tmp_path)

    assert data is not None
    summary = format_unfinished_job_summary(data)
    assert "Dateien: 0/1" in summary
    assert Path(file_path).name in summary


def test_resume_plan_requeues_open_and_running_files(tmp_path):
    from dragontools.core.job_journal import JobJournal, build_resume_plan

    files = [
        str(tmp_path / "ok.mkv"),
        str(tmp_path / "running.mkv"),
        str(tmp_path / "queued.mkv"),
        str(tmp_path / "failed.mkv"),
    ]
    journal = JobJournal.start(
        files=files,
        codec="h265",
        mode="convert",
        root=tmp_path,
    )
    journal.finish_file(files[0], status="ok")
    journal.start_file(files[1], index=2, total=4)
    journal.finish_file(files[3], status="error", message="Fehler")

    plan = build_resume_plan(journal.data)

    assert plan["codec"] == "h265"
    assert plan["mode"] == "convert"
    assert plan["files"] == [files[1], files[2]]
    assert plan["counts"]["ok"] == 1
    assert plan["counts"]["running"] == 1
    assert plan["counts"]["queued"] == 1
    assert plan["counts"]["failed"] == 1


def test_job_journal_tracks_multiple_parallel_current_files(tmp_path):
    from dragontools.core.job_journal import (
        JobJournal,
        build_resume_plan,
        format_unfinished_job_summary,
    )

    files = [
        str(tmp_path / "a.mkv"),
        str(tmp_path / "b.mkv"),
        str(tmp_path / "c.mkv"),
    ]
    journal = JobJournal.start(
        files=files,
        codec="h265",
        mode="convert",
        root=tmp_path,
    )

    journal.start_file(files[0], index=1, total=3)
    journal.start_file(files[1], index=2, total=3)

    assert journal.data["current_files"] == [files[0], files[1]]
    assert journal.data["current_file"] == files[1]

    journal.finish_file(files[0], status="ok")

    assert journal.data["current_files"] == [files[1]]
    assert journal.data["current_file"] == files[1]

    summary = format_unfinished_job_summary(journal.data)
    assert "Letzte Datei" in summary
    assert Path(files[1]).name in summary

    plan = build_resume_plan(journal.data)
    assert plan["current_files"] == [files[1]]
    assert plan["files"] == [files[1], files[2]]


def test_resume_plan_can_include_failed_files(tmp_path):
    from dragontools.core.job_journal import JobJournal, build_resume_plan

    failed = str(tmp_path / "failed.mkv")
    queued = str(tmp_path / "queued.mkv")
    journal = JobJournal.start(
        files=[failed, queued],
        codec="av1",
        mode="convert",
        root=tmp_path,
    )
    journal.finish_file(failed, status="warn", message="zu groß")

    plan = build_resume_plan(journal.data, retry_failed=True)

    assert plan["codec"] == "av1"
    assert plan["files"] == [failed, queued]


def test_archive_active_job_journal_removes_active_file(tmp_path):
    from dragontools.core.job_journal import (
        JobJournal,
        archive_active_job_journal,
        read_active_job_journal,
    )

    file_path = str(tmp_path / "a.mkv")
    journal = JobJournal.start(files=[file_path], codec="h265", mode="convert", root=tmp_path)

    archive = archive_active_job_journal(status="restored_to_queue", root=tmp_path)

    assert archive is not None
    assert archive.exists()
    assert "restored_to_queue" in archive.name
    assert read_active_job_journal(tmp_path) is None
    assert not journal.path.exists()


def test_job_journal_uses_unique_files_for_overlapping_runs(tmp_path):
    from dragontools.core.job_journal import (
        JobJournal,
        read_active_job_journals,
    )

    first = JobJournal.start(
        files=[str(tmp_path / "a.mkv")],
        codec="h265",
        mode="convert",
        root=tmp_path,
    )
    second = JobJournal.start(
        files=[str(tmp_path / "b.mkv")],
        codec="h265",
        mode="convert",
        root=tmp_path,
    )

    assert first.path != second.path
    assert first.path.exists()
    assert second.path.exists()
    journals = read_active_job_journals(tmp_path)
    assert {item["run_id"] for item in journals} == {
        first.data["run_id"],
        second.data["run_id"],
    }


def test_job_journal_start_fails_closed_on_disk_full(tmp_path, monkeypatch):
    import pytest
    from dragontools.core import job_journal
    from dragontools.core.job_journal import JobJournal, JobJournalWriteError

    messages: list[str] = []

    def fail_write(_path, _data):
        raise OSError("disk full")

    monkeypatch.setattr(job_journal, "_atomic_write_json", fail_write)

    with pytest.raises(JobJournalWriteError, match="disk full"):
        JobJournal.start(
            files=[str(tmp_path / "a.mkv")],
            codec="h265",
            mode="convert",
            root=tmp_path,
            on_write_error=messages.append,
        )

    assert messages
    assert "disk full" in messages[-1]
    assert not list((tmp_path / "JobJournal").glob("run_*.json"))


def test_job_journal_start_fails_closed_on_permission_denied(tmp_path, monkeypatch):
    import pytest
    from dragontools.core import job_journal
    from dragontools.core.job_journal import JobJournal, JobJournalWriteError

    monkeypatch.setattr(
        job_journal,
        "_atomic_write_json",
        lambda _path, _data: (_ for _ in ()).throw(PermissionError("permission denied")),
    )

    with pytest.raises(JobJournalWriteError, match="permission denied"):
        JobJournal.start(
            files=[str(tmp_path / "a.mkv")],
            codec="h265",
            mode="convert",
            root=tmp_path,
        )


def test_job_journal_start_propagates_atomic_replace_failure(tmp_path, monkeypatch):
    import pytest
    from dragontools.core import json_io
    from dragontools.core.job_journal import JobJournal, JobJournalWriteError

    def fail_replace(_src, _dst):
        raise OSError("atomic replace failed")

    monkeypatch.setattr(json_io.os, "replace", fail_replace)

    with pytest.raises(JobJournalWriteError, match="atomic replace failed"):
        JobJournal.start(
            files=[str(tmp_path / "a.mkv")],
            codec="h265",
            mode="convert",
            root=tmp_path,
        )

    assert not list((tmp_path / "JobJournal").glob("*.tmp"))


def test_job_journal_archive_failure_keeps_active_journal_recoverable(tmp_path, monkeypatch):
    import pytest
    from dragontools.core import job_journal
    from dragontools.core.job_journal import (
        JobJournal,
        JobJournalWriteError,
        read_job_journal_path,
    )

    journal = JobJournal.start(
        files=[str(tmp_path / "a.mkv")],
        codec="h265",
        mode="convert",
        root=tmp_path,
    )
    durable_before = journal.path.read_bytes()
    real_write = job_journal._atomic_write_json

    def fail_archive(path, data):
        if path.parent.name == job_journal.ARCHIVE_DIR_NAME:
            raise OSError("archive disk full")
        return real_write(path, data)

    monkeypatch.setattr(job_journal, "_atomic_write_json", fail_archive)

    with pytest.raises(JobJournalWriteError, match="archive disk full"):
        journal.finish_run(status="completed")

    assert journal.path.exists()
    assert journal.path.read_bytes() == durable_before
    recovered = read_job_journal_path(journal.path)
    assert recovered is not None
    assert recovered["active"] is True
    assert recovered["status"] == "running"
    assert not list((tmp_path / "JobJournal" / "Abgeschlossen").glob("*.json"))


def test_job_journal_write_failure_preserves_last_durable_file(tmp_path, monkeypatch):
    import pytest
    from dragontools.core import job_journal
    from dragontools.core.job_journal import JobJournal, JobJournalWriteError

    file_path = str(tmp_path / "a.mkv")
    journal = JobJournal.start(
        files=[file_path],
        codec="h265",
        mode="convert",
        root=tmp_path,
    )
    durable_before = journal.path.read_bytes()

    monkeypatch.setattr(
        job_journal,
        "_atomic_write_json",
        lambda _path, _data: (_ for _ in ()).throw(OSError("write failed")),
    )

    with pytest.raises(JobJournalWriteError, match="write failed"):
        journal.start_file(file_path, index=1, total=1)

    assert journal.path.read_bytes() == durable_before
