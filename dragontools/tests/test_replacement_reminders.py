from __future__ import annotations

from datetime import datetime


def test_replacement_reminder_persists_with_unique_ids(tmp_path):
    from dragontools.core.replacement_reminders import (
        add_replacement_reminder,
        list_replacement_reminders,
    )

    path = tmp_path / "reminders.json"
    fixed = datetime(2026, 8, 31, 21, 38, 45)

    first = add_replacement_reminder(
        series_name="Serie 1",
        season=1,
        episode=3,
        episode_label="S01E03",
        old_paths=[tmp_path / "Serie 1 - S01E03 - Alt.mkv"],
        new_path=tmp_path / "Serie 1 - S01E03 - Neu.mp4",
        reason="Gleiche SxxExx-Kennung im Ziel-Staffelordner",
        path=path,
        now=fixed,
    )
    second = add_replacement_reminder(
        series_name="Serie 1",
        season=1,
        episode=4,
        episode_label="S01E04",
        old_paths=[tmp_path / "Serie 1 - S01E04 - Alt.mkv"],
        new_path=tmp_path / "Serie 1 - S01E04 - Neu.mp4",
        reason="Gleiche SxxExx-Kennung im Ziel-Staffelordner",
        path=path,
        now=fixed,
    )

    assert first["id"] == "#20260831-213845-001"
    assert second["id"] == "#20260831-213845-002"
    assert len(list_replacement_reminders(path)) == 2


def test_replacement_reminder_confirm_deletes_defer_and_close_keep(tmp_path):
    from dragontools.core.replacement_reminders import (
        add_replacement_reminder,
        dismiss_replacement_reminders,
        list_replacement_reminders,
    )

    path = tmp_path / "reminders.json"
    reminder = add_replacement_reminder(
        series_name="Serie 1",
        season=1,
        episode=3,
        episode_label="S01E03",
        old_paths=[tmp_path / "Alt.mkv"],
        new_path=tmp_path / "Neu.mp4",
        reason="Test",
        path=path,
        now=datetime(2026, 8, 31, 21, 38, 45),
    )

    # Erneut vorlegen oder Fenster-X ruft bewusst keine Löschung auf.
    assert [item["id"] for item in list_replacement_reminders(path)] == [reminder["id"]]
    assert [item["id"] for item in list_replacement_reminders(path)] == [reminder["id"]]

    removed = dismiss_replacement_reminders([reminder["id"]], path)

    assert removed == 1
    assert list_replacement_reminders(path) == []


def test_replacement_reminder_survives_shutdown_until_next_start(tmp_path):
    from dragontools.core.replacement_reminders import (
        add_replacement_reminder,
        list_replacement_reminders,
    )

    path = tmp_path / "reminders.json"
    add_replacement_reminder(
        series_name="Serie 1",
        season=1,
        episode=3,
        episode_label="S01E03",
        old_paths=[tmp_path / "Alt.mkv"],
        new_path=tmp_path / "Neu.mp4",
        reason="Shutdown-Test",
        path=path,
        now=datetime(2026, 8, 31, 21, 38, 45),
    )

    next_start = list_replacement_reminders(path)

    assert len(next_start) == 1
    assert next_start[0]["reason"] == "Shutdown-Test"
