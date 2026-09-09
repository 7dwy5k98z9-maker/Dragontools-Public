from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_recovery_rolls_back_sidecar_when_video_staging_still_exists(tmp_path):
    from dragontools.core.sidecar_journal import SidecarJournal, recover_active_sidecar_journals

    video_staging = tmp_path / "film.__tmp__.mkv"
    video_dest = tmp_path / "film.mkv"
    source = tmp_path / "film.__tmp__.de.srt"
    destination = tmp_path / "film.de.srt"
    backup = tmp_path / "film.de.srt.dragontools_backup"
    _write(video_staging, "VIDEO-STAGING")
    _write(source, "NEW")
    _write(destination, "OLD")

    journal = SidecarJournal.start(
        video_staging=video_staging,
        video_destination=video_dest,
        records=[{"source": str(source), "destination": str(destination), "backup": str(backup)}],
        root=tmp_path,
    )
    os.replace(destination, backup)  # Hard-Crash-Fenster direkt nach Altbestand->Backup

    result = recover_active_sidecar_journals(tmp_path)

    assert result["rolled_back"] == 1
    assert destination.read_text(encoding="utf-8") == "OLD"
    assert source.read_text(encoding="utf-8") == "NEW"
    assert not backup.exists()
    assert not journal.path.exists()


def test_recovery_completes_sidecar_when_video_commit_is_visible(tmp_path):
    from dragontools.core.sidecar_journal import SidecarJournal, recover_active_sidecar_journals

    video_staging = tmp_path / "film.__tmp__.mkv"
    video_dest = tmp_path / "film.mkv"
    source = tmp_path / "film.__tmp__.de.srt"
    destination = tmp_path / "film.de.srt"
    backup = tmp_path / "film.de.srt.dragontools_backup"
    _write(video_dest, "FINAL-VIDEO")
    _write(source, "NEW")
    _write(destination, "OLD")

    journal = SidecarJournal.start(
        video_staging=video_staging,
        video_destination=video_dest,
        records=[{"source": str(source), "destination": str(destination), "backup": str(backup)}],
        root=tmp_path,
    )

    result = recover_active_sidecar_journals(tmp_path)

    assert result["completed"] == 1
    assert destination.read_text(encoding="utf-8") == "NEW"
    assert backup.read_text(encoding="utf-8") == "OLD"
    assert not source.exists()
    assert not journal.path.exists()


def test_video_committed_flag_completes_even_if_video_path_is_same(tmp_path):
    from dragontools.core.sidecar_journal import SidecarJournal, recover_active_sidecar_journals

    video = tmp_path / "film.mkv"
    source = tmp_path / "film.__tmp__.de.srt"
    destination = tmp_path / "film.de.srt"
    _write(video, "FINAL")
    _write(source, "NEW")

    SidecarJournal.start(
        video_staging=video,
        video_destination=video,
        records=[{"source": str(source), "destination": str(destination), "backup": ""}],
        root=tmp_path,
        video_committed=True,
    )

    result = recover_active_sidecar_journals(tmp_path)
    assert result["completed"] == 1
    assert destination.read_text(encoding="utf-8") == "NEW"
    assert not source.exists()


def test_sidecar_plan_is_prepared_before_any_mutation(tmp_path):
    from dragontools.core.sidecar_transaction import SidecarCommitTransaction

    source = tmp_path / "film.__tmp__.de.srt"
    destination = tmp_path / "film.de.srt"
    _write(source, "NEW")
    _write(destination, "OLD")

    tx = SidecarCommitTransaction(
        [str(source)],
        source_base=tmp_path / "film.__tmp__",
        destination_base=tmp_path / "film",
    )
    records = tx.prepare_records()

    assert source.read_text(encoding="utf-8") == "NEW"
    assert destination.read_text(encoding="utf-8") == "OLD"
    assert records[0]["source"] == str(source)
    assert records[0]["destination"] == str(destination)
    assert records[0]["backup"].endswith("film.de.srt.dragontools_backup")


def test_journal_write_failure_blocks_sidecar_mutation(monkeypatch, tmp_path):
    import dragontools.worker.workflow_output_commit as module
    from dragontools.core.sidecar_journal import SidecarJournalWriteError

    source = tmp_path / "film.__tmp__.de.srt"
    destination = tmp_path / "film.de.srt"
    _write(source, "NEW")
    _write(destination, "OLD")

    monkeypatch.setattr(
        module.SidecarJournal,
        "start",
        lambda **_: (_ for _ in ()).throw(SidecarJournalWriteError("disk full")),
    )
    coordinator = module.WorkflowOutputCommitCoordinator(
        replace_service=SimpleNamespace(),
        logger=SimpleNamespace(info=lambda *_: None, warn=lambda *_: None, error=lambda *_: None),
        result_service=SimpleNamespace(),
        sidecar_outputs={},
        postprocess_outputs={},
    )
    ctx = SimpleNamespace(
        sidecar_paths=[str(source)],
        output_path=str(tmp_path / "film.__tmp__.mkv"),
        input_path=str(tmp_path / "source.mkv"),
    )

    with pytest.raises(SidecarJournalWriteError):
        coordinator._commit_sidecars(ctx, final_output=str(tmp_path / "film.mkv"), store_result=False)

    assert source.read_text(encoding="utf-8") == "NEW"
    assert destination.read_text(encoding="utf-8") == "OLD"
