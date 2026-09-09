from __future__ import annotations

from types import SimpleNamespace


def test_schedule_system_shutdown_uses_short_windows_buffer(monkeypatch):
    from dragontools.core import system_shutdown
    from dragontools.core import windows_restart_policy

    calls = []
    allowed = []
    monkeypatch.setattr(system_shutdown.os, "name", "nt", raising=False)
    monkeypatch.setattr(system_shutdown.subprocess, "CREATE_NO_WINDOW", 123, raising=False)
    monkeypatch.setattr(windows_restart_policy, "_USER_SHUTDOWN_ALLOWED_UNTIL", 0.0)
    monkeypatch.setattr(
        system_shutdown.subprocess,
        "run",
        lambda cmd, **kwargs: calls.append((cmd, kwargs)) or SimpleNamespace(returncode=0),
    )
    monkeypatch.setattr(
        system_shutdown,
        "allow_user_initiated_shutdown",
        lambda: allowed.append(True),
    )

    logs = []
    ok = system_shutdown.schedule_system_shutdown(
        delay_seconds=5,
        log=lambda msg, level="info": logs.append((level, msg)),
    )

    assert ok is True
    assert len(calls) == 1
    cmd, kwargs = calls[0]
    assert cmd[1:] == ["/s", "/t", "5"]
    assert str(cmd[0]).lower().endswith("shutdown.exe") or cmd[0] == "shutdown"
    assert kwargs["check"] is True
    assert kwargs["creationflags"] == 123
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert kwargs["timeout"] == 15
    assert allowed == [True]
    assert any("5 Sekunden" in msg for _level, msg in logs)


def test_schedule_system_shutdown_returns_false_on_failure(monkeypatch):
    from dragontools.core import system_shutdown

    cleared = []
    monkeypatch.setattr(system_shutdown.os, "name", "nt", raising=False)
    monkeypatch.setattr(
        system_shutdown,
        "clear_user_initiated_shutdown",
        lambda: cleared.append(True),
    )

    def fail(*_args, **_kwargs):
        raise OSError("blocked")

    monkeypatch.setattr(system_shutdown.subprocess, "run", fail)
    logs = []

    ok = system_shutdown.schedule_system_shutdown(
        delay_seconds=5,
        log=lambda msg, level="info": logs.append((level, msg)),
    )

    assert ok is False
    assert cleared == [True]
    assert any("fehlgeschlagen" in msg for _level, msg in logs)
