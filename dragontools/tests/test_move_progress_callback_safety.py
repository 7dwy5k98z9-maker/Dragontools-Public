from __future__ import annotations

from pathlib import Path


def _service(logs):
    from dragontools.core.move_file_service import MoveFileService

    return MoveFileService(
        conflict_mode="skip",
        log=lambda message, level="info": logs.append((level, message)),
        wait=lambda: None,
        abort_immediately=lambda: False,
        journal=None,
    )


def test_progress_callback_failure_does_not_break_successful_hardlink_move(tmp_path):
    source = tmp_path / "source" / "film.mkv"
    target = tmp_path / "target"
    source.parent.mkdir()
    source.write_bytes(b"payload")
    logs = []

    ok, result = _service(logs).move(
        source,
        target,
        hook=lambda _amount: (_ for _ in ()).throw(RuntimeError("Qt object deleted")),
    )

    destination = target / source.name
    assert ok is True
    assert result["ok"] is True
    assert destination.read_bytes() == b"payload"
    assert not source.exists()
    assert any("Fortschritts-Callback" in message for _level, message in logs)


def test_progress_callback_failure_does_not_break_copy_fallback(tmp_path, monkeypatch):
    import dragontools.core.move_file_service as module

    source = tmp_path / "source" / "film.mkv"
    target = tmp_path / "target"
    source.parent.mkdir()
    source.write_bytes(b"x" * (9 * 1024 * 1024))
    logs = []
    monkeypatch.setattr(module.os, "link", lambda *_args: (_ for _ in ()).throw(OSError("cross-device")))

    ok, _result = _service(logs).move(
        source,
        target,
        hook=lambda _amount: (_ for _ in ()).throw(ValueError("dead progress sink")),
    )

    destination = target / source.name
    assert ok is True
    assert destination.stat().st_size == 9 * 1024 * 1024
    assert not source.exists()
    assert sum("Fortschritts-Callback" in message for _level, message in logs) == 1
