from __future__ import annotations

import pytest

from dragontools.core import process_runner


def test_run_analysis_tool_wraps_oserror_as_runtimeerror(monkeypatch):
    def fail_run(*_args, **_kwargs):
        raise OSError("start failed")

    monkeypatch.setattr(process_runner.subprocess, "run", fail_run)

    with pytest.raises(RuntimeError, match="Analyse-Tool konnte nicht gestartet") as exc_info:
        process_runner.run_analysis_tool(["ffprobe", "input.mkv"])

    assert isinstance(exc_info.value.__cause__, OSError)


def test_run_analysis_tool_does_not_hide_programming_errors(monkeypatch):
    def fail_run(*_args, **_kwargs):
        raise ValueError("bad test/programming input")

    monkeypatch.setattr(process_runner.subprocess, "run", fail_run)

    with pytest.raises(ValueError, match="bad test/programming input"):
        process_runner.run_analysis_tool(["ffprobe", "input.mkv"])
