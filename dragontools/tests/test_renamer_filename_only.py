"""Renaming must not open video contents, including its recovery journal."""
from pathlib import Path

import pytest

from dragontools.core.movie_renamer import rename_movie_file
from dragontools.core import sidecar_journal


def forbid_video_reads(monkeypatch):
    original = Path.open

    def guarded_open(path, *args, **kwargs):
        if path.suffix.lower() == ".mkv":
            raise AssertionError("Renamer must not open video contents")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)


@pytest.mark.parametrize("companions", [False, True])
def test_rename_never_opens_video_contents(tmp_path, monkeypatch, companions):
    source = tmp_path / "Alt.mkv"
    source.write_bytes(b"video")
    sub = tmp_path / "Alt.de.srt"
    if companions:
        sub.write_text("subtitle", encoding="utf-8")
    monkeypatch.setattr(sidecar_journal, "app_documents_dir", lambda root=None: tmp_path / "docs")
    forbid_video_reads(monkeypatch)
    target = rename_movie_file(source, "Neu.mkv")
    assert target == tmp_path / "Neu.mkv"
    assert target.exists() and not source.exists()
    if companions:
        assert (tmp_path / "Neu.de.srt").read_text(encoding="utf-8") == "subtitle"
        assert not sub.exists()


@pytest.mark.parametrize("committed", [False, True])
def test_rename_recovery_never_reads_video(tmp_path, monkeypatch, committed):
    source, target = tmp_path / "Alt.mkv", tmp_path / "Neu.mkv"
    source.write_bytes(b"video")
    sub, sub_target = tmp_path / "Alt.de.srt", tmp_path / "Neu.de.srt"
    sub.write_text("subtitle", encoding="utf-8")
    forbid_video_reads(monkeypatch)
    journal = sidecar_journal.SidecarJournal.start(
        video_staging=source, video_destination=target, rename_only=True, root=tmp_path,
        records=[{"source": str(sub), "destination": str(sub_target), "backup": ""}],
    )
    assert journal.data["video_receipt"] is None
    assert journal.data["video_rename_identity"]
    sub.rename(sub_target)
    if committed:
        source.rename(target)
    result = sidecar_journal.recover_active_sidecar_journals(tmp_path)
    assert result["completed" if committed else "rolled_back"] == 1
    assert not journal.path.exists()
    assert (sub_target if committed else sub).exists()
    assert not (sub if committed else sub_target).exists()


@pytest.mark.parametrize("broken_identity", [False, None, 42])
def test_recovery_cannot_accept_unrelated_video_at_target(tmp_path, monkeypatch, broken_identity):
    source, target = tmp_path / "Alt.mkv", tmp_path / "Neu.mkv"
    source.write_bytes(b"video")
    sub, sub_target = tmp_path / "Alt.de.srt", tmp_path / "Neu.de.srt"
    sub.write_text("subtitle", encoding="utf-8")
    journal = sidecar_journal.SidecarJournal.start(
        video_staging=source, video_destination=target, rename_only=True, root=tmp_path,
        records=[{"source": str(sub), "destination": str(sub_target), "backup": ""}],
    )
    source.rename(tmp_path / "Elsewhere.mkv")
    if broken_identity is not False:
        journal.data["video_rename_identity"] = broken_identity
        journal.write(fatal=True)
    target.write_bytes(b"unrelated")
    sub.rename(sub_target)
    forbid_video_reads(monkeypatch)
    result = sidecar_journal.recover_active_sidecar_journals(tmp_path)
    assert result["pending"] == 1
    assert journal.path.exists()
    assert sub_target.read_text(encoding="utf-8") == "subtitle"
    assert target.exists() and (tmp_path / "Elsewhere.mkv").exists()


def test_regular_sidecar_commit_keeps_full_video_receipt(tmp_path):
    source = tmp_path / "Alt.mkv"
    source.write_bytes(b"video")
    sub = tmp_path / "Alt.de.srt"
    sub.write_text("subtitle", encoding="utf-8")
    journal = sidecar_journal.SidecarJournal.start(
        video_staging=source, video_destination=tmp_path / "Neu.mkv", root=tmp_path,
        records=[{"source": str(sub), "destination": str(tmp_path / "Neu.de.srt"), "backup": ""}],
    )
    assert journal.data["video_receipt"]["content"]
    assert "video_rename_identity" not in journal.data
    journal.finish()
