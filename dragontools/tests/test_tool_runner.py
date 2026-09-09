from __future__ import annotations

import sys

import pytest

from dragontools.worker.tool_runner import _terminate_plain, run_tool


def test_run_tool_collects_stdout_and_stderr():
    result = run_tool(
        [
            sys.executable,
            "-c",
            "import sys; print('out-ok'); print('err-ok', file=sys.stderr)",
        ],
        label="Test-Tool",
        timeout_s=10,
    )

    assert result.ok
    assert "out-ok" in result.stdout
    assert "err-ok" in result.stderr


def test_run_tool_reports_timeout():
    result = run_tool(
        [sys.executable, "-c", "import time; time.sleep(2)"],
        label="Langsames Test-Tool",
        timeout_s=0.2,
    )

    assert result.timed_out is True
    assert result.returncode == 124


def test_terminate_plain_logs_terminate_and_kill_failures():
    class FakeProc:
        def poll(self):
            return None

        def terminate(self):
            raise OSError("terminate denied")

        def kill(self):
            raise OSError("kill denied")

    logs = []
    _terminate_plain(FakeProc(), log=lambda msg, level: logs.append((level, msg)), label="FFmpeg")

    assert any("terminate()" in msg for _level, msg in logs)
    assert any(level == "error" and "kill() fehlgeschlagen" in msg for level, msg in logs)


def test_terminate_plain_does_not_swallow_unexpected_programming_error():
    class FakeProc:
        def poll(self):
            return None

        def terminate(self):
            raise RuntimeError("unexpected")

    with pytest.raises(RuntimeError, match="unexpected"):
        _terminate_plain(FakeProc())
