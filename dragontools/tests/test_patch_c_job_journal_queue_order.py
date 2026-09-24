from __future__ import annotations

from dragontools.core.job_journal import JobJournal
from dragontools.core.job_journal_resume import build_resume_plan


def test_job_journal_persists_manual_queue_order_and_live_add(tmp_path):
    journal = JobJournal.start(
        files=["a.mkv", "b.mkv", "c.mkv"],
        codec="h265",
        mode="convert",
        root=tmp_path,
    )
    journal.update_queue_order(["c.mkv", "a.mkv", "new.mkv", "b.mkv"])

    assert journal.data["queue_order"] == ["c.mkv", "a.mkv", "new.mkv", "b.mkv"]
    assert journal.data["files"]["new.mkv"]["status"] == "queued"
    plan = build_resume_plan(journal.data)
    assert plan["files"] == ["c.mkv", "a.mkv", "new.mkv", "b.mkv"]


def test_removed_queued_file_is_not_reintroduced_by_resume_plan(tmp_path):
    journal = JobJournal.start(
        files=["a.mkv", "b.mkv", "c.mkv"],
        codec="h265",
        mode="convert",
        root=tmp_path,
    )
    journal.update_queue_order(["a.mkv", "c.mkv"])

    plan = build_resume_plan(journal.data)
    assert plan["files"] == ["a.mkv", "c.mkv"]
    assert "b.mkv" not in plan["files"]


def test_legacy_journal_without_queue_order_keeps_original_dict_order():
    data = {
        "files": {
            "a.mkv": {"status": "queued"},
            "b.mkv": {"status": "queued"},
        }
    }
    assert build_resume_plan(data)["files"] == ["a.mkv", "b.mkv"]
