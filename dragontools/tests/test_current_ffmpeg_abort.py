from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest


def test_terminate_current_ffmpeg_only_kills_matching_ffmpeg(monkeypatch):
    pytest.importorskip("PyQt6")
    import dragontools.worker.converter_control as module
    from dragontools.worker.converter_control import ConverterControlService

    calls = []

    class FakeProcess:
        args = ["ffmpeg", "-i", "input.mkv"]

        def poll(self):
            return None

    worker = SimpleNamespace(
        _files_lock=threading.Lock(),
        _queue=SimpleNamespace(current_file="C:/Video/current.mkv"),
        _lock=threading.Lock(),
        _current_process=FakeProcess(),
        abort_requested=False,
        abort_type=None,
        log=lambda *args: None,
    )

    monkeypatch.setattr(
        module,
        "terminate_process_tree",
        lambda *args, **kwargs: calls.append((args, kwargs)) or True,
    )

    stopped = ConverterControlService(worker).terminate_current_ffmpeg("C:/Video/current.mkv")

    assert stopped is True
    assert len(calls) == 1
    assert worker.abort_requested is False
    assert worker.abort_type is None


def test_terminate_current_ffmpeg_rejects_other_current_file(monkeypatch):
    pytest.importorskip("PyQt6")
    import dragontools.worker.converter_control as module
    from dragontools.worker.converter_control import ConverterControlService

    class FakeProcess:
        args = ["ffmpeg", "-i", "input.mkv"]

        def poll(self):
            return None

    worker = SimpleNamespace(
        _files_lock=threading.Lock(),
        _queue=SimpleNamespace(current_file="C:/Video/current.mkv"),
        _lock=threading.Lock(),
        _current_process=FakeProcess(),
        log=lambda *args: None,
    )
    monkeypatch.setattr(
        module,
        "terminate_process_tree",
        lambda *args, **kwargs: pytest.fail("wrong file must not terminate FFmpeg"),
    )

    assert ConverterControlService(worker).terminate_current_ffmpeg("C:/Video/other.mkv") is False

def test_taskkill_tree_uses_bounded_timeout(monkeypatch):
    from dragontools.worker import process_control as module

    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module._taskkill_tree(1234, timeout=2.5) is True
    assert calls[0][0] == ["taskkill", "/PID", "1234", "/T", "/F"]
    assert calls[0][1]["timeout"] == 2.5
    assert calls[0][1]["check"] is False


def test_taskkill_tree_timeout_returns_for_python_fallback(monkeypatch):
    from dragontools.worker import process_control as module

    log_entries = []

    def fake_run(args, **kwargs):
        raise module.subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module._taskkill_tree(4321, timeout=1.0, log=lambda *args: log_entries.append(args)) is False
    assert any("taskkill-Timeout" in entry[0] for entry in log_entries)



def test_taskkill_tree_oserror_returns_false_for_fallback(monkeypatch):
    from dragontools.worker import process_control as module

    log_entries = []

    def fake_run(*_args, **_kwargs):
        raise OSError("taskkill nicht startbar")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module._taskkill_tree(9876, log=lambda *args: log_entries.append(args)) is False
    assert any("taskkill fehlgeschlagen" in entry[0] for entry in log_entries)
