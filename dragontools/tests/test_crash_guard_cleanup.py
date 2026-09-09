from __future__ import annotations

import json


def test_clear_activity_removes_empty_fatal_runtime_log(tmp_path, monkeypatch):
    from dragontools.core import crash_guard

    state_file = tmp_path / "crash_state.json"
    fatal_file = tmp_path / "20260813_120000_fatal_runtime.txt"
    state_file.write_text("{}", encoding="utf-8")
    fatal_file.write_text("", encoding="utf-8")
    handle = open(fatal_file, "a", encoding="utf-8")

    monkeypatch.setattr(crash_guard, "_state_file", state_file)
    monkeypatch.setattr(crash_guard, "_fatal_log_file", fatal_file)
    monkeypatch.setattr(crash_guard, "_fatal_log_handle", handle)

    crash_guard.clear_activity()

    assert not state_file.exists()
    assert not fatal_file.exists()


def test_unclean_report_removes_empty_previous_fatal_runtime_log(tmp_path, monkeypatch):
    from dragontools.core import crash_guard

    state_file = tmp_path / "crash_state.json"
    fatal_file = tmp_path / "20260813_120000_fatal_runtime.txt"
    fatal_file.write_text("", encoding="utf-8")
    state = {
        "active": True,
        "pid": 999999,
        "timestamp": "2026-08-13 12:00:00",
        "stage": "FFmpeg-Encode laeuft",
        "extra": {"fatal_log": str(fatal_file)},
    }
    state_file.write_text(json.dumps(state), encoding="utf-8")

    monkeypatch.setattr(crash_guard, "_state_file", state_file)
    monkeypatch.setattr(crash_guard, "_pid_is_running", lambda _pid: False)

    crash_guard._report_unclean_previous_run("9.0")

    reports = list(tmp_path.glob("*_unclean_shutdown.txt"))
    assert len(reports) == 1
    assert not state_file.exists()
    assert not fatal_file.exists()
