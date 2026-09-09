from __future__ import annotations

import ast
import sys
from pathlib import Path

from dragontools.core.timeout_settings import get_default
from dragontools.worker.tool_runner import run_tool, run_tool_bytes


PROJECT_PACKAGE = Path(__file__).resolve().parents[1]


def _direct_popen_calls(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "Popen"
            and isinstance(func.value, ast.Name)
            and func.value.id == "subprocess"
        ):
            lines.append(node.lineno)
    return lines


def test_block3_aux_workers_have_no_direct_popen_calls():
    files = [
        "audio_mux_thread.py",
        "mp4_remux_thread.py",
        "merge_thread.py",
        "iso_thread.py",
        "dv_remux_components.py",
        "audio_video_match_thread.py",
    ]
    offenders = {
        name: _direct_popen_calls(PROJECT_PACKAGE / "worker" / name)
        for name in files
    }
    assert offenders == {name: [] for name in files}



def test_tool_runner_delegates_shared_process_lifecycle():
    runner = (PROJECT_PACKAGE / "worker" / "tool_runner.py").read_text(encoding="utf-8")
    lifecycle = (PROJECT_PACKAGE / "worker" / "tool_process_lifecycle.py").read_text(encoding="utf-8")

    assert len(runner.splitlines()) < 360
    assert "ProcessLifecycle" in runner
    assert "class ProcessLifecycle" in lifecycle
    assert "PyQt6" not in lifecycle

def test_worker_media_and_avmatch_timeouts_have_safe_defaults():
    assert get_default("worker_media_process") == 300
    assert get_default("avmatch_process") == 14_400


def test_run_tool_inactivity_timeout_is_reset_by_output():
    result = run_tool(
        [
            sys.executable,
            "-u",
            "-c",
            (
                "import time\n"
                "for i in range(6):\n"
                "    print(i, flush=True)\n"
                "    time.sleep(0.30)\n"
            ),
        ],
        label="Inactivity-Test",
        timeout_s=2.5,
        timeout_mode="inactivity",
    )
    assert result.ok
    assert result.timed_out is False
    assert result.stdout.splitlines() == ["0", "1", "2", "3", "4", "5"]


def test_run_tool_line_callback_receives_live_output():
    seen: list[str] = []
    result = run_tool(
        [sys.executable, "-u", "-c", "print('alpha'); print('beta')"],
        timeout_s=5,
        stdout_line=seen.append,
    )

    assert result.ok
    assert seen == ["alpha", "beta"]


def test_run_tool_bytes_preserves_binary_stdout():
    result = run_tool_bytes(
        [
            sys.executable,
            "-c",
            "import os,sys; os.write(sys.stdout.fileno(), b'\\x00\\xffABC')",
        ],
        timeout_s=5,
    )

    assert result.ok
    assert result.stdout == b"\x00\xffABC"


def test_run_tool_timeout_kills_spawned_child_on_posix():
    import os
    import time

    if os.name == "nt":
        # Windows wird produktiv über taskkill /T /F abgedeckt; dieser Test
        # prüft gezielt die POSIX-Prozessgruppen-Implementierung.
        return

    result = run_tool(
        [
            sys.executable,
            "-u",
            "-c",
            (
                "import subprocess,sys,time\n"
                "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
                "print(child.pid, flush=True)\n"
                "time.sleep(30)\n"
            ),
        ],
        label="Process-tree-Test",
        timeout_s=2.5,
    )

    assert result.timed_out
    child_pid = int(result.stdout.splitlines()[0])

    def _still_running(pid: int) -> bool:
        proc_stat = Path(f"/proc/{pid}/stat")
        if proc_stat.exists():
            try:
                state = proc_stat.read_text(encoding="utf-8").split()[2]
                return state != "Z"
            except (OSError, IndexError):
                pass
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    deadline = time.monotonic() + 2.0
    while _still_running(child_pid) and time.monotonic() < deadline:
        time.sleep(0.05)

    assert not _still_running(child_pid)


def test_run_tool_merge_stderr_uses_single_drain_without_crashing():
    seen: list[str] = []
    result = run_tool(
        [
            sys.executable,
            "-u",
            "-c",
            "import sys; print('stdout-line'); print('stderr-line', file=sys.stderr)",
        ],
        timeout_s=5,
        merge_stderr=True,
        stdout_line=seen.append,
    )

    assert result.ok
    assert result.stderr == ""
    assert "stdout-line" in result.stdout
    assert "stderr-line" in result.stdout
    assert set(seen) == {"stdout-line", "stderr-line"}


def test_run_tool_marks_immediate_worker_abort_consistently():
    import threading

    class Worker:
        def __init__(self):
            self._process_lock = threading.Lock()
            self._current_process = None
            self.abort_requested = False
            self.abort_type = None

    worker = Worker()

    def _request_abort() -> None:
        import time
        time.sleep(0.35)
        worker.abort_requested = True
        worker.abort_type = "sofort"

    trigger = threading.Thread(target=_request_abort, daemon=True)
    trigger.start()
    result = run_tool(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        label="Abort-Test",
        timeout_s=10,
        worker=worker,
    )
    trigger.join(timeout=2)

    assert result.aborted is True
    assert result.returncode == 130
    assert worker._current_process is None
