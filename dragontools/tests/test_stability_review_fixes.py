from __future__ import annotations

import gc
import sys
import threading
import warnings
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
from types import SimpleNamespace


def test_tool_runner_does_not_leave_resource_warnings():
    from dragontools.worker.tool_runner import run_tool

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ResourceWarning)
        for _ in range(3):
            result = run_tool(
                [sys.executable, "-c", "import sys; print('ok'); print('err', file=sys.stderr)"],
                timeout_s=10,
                label="Resource-Test",
            )
            assert result.returncode == 0
        gc.collect()

    assert not [w for w in caught if issubclass(w.category, ResourceWarning)]


def test_converter_progress_run_closes_pipes_without_resource_warning():
    from dragontools.worker.converter_progress import ConverterProgressHelper

    class Worker:
        def __init__(self):
            self._lock = threading.Lock()
            self._current_process = None
            self._paused = False
            self.abort_requested = False
            self.abort_type = None

        def wait_if_paused(self):
            return None

        def log(self, _message, _level="info"):
            return None

    helper = ConverterProgressHelper(Worker())
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ResourceWarning)
        assert helper.run([sys.executable, "-c", "print('ok')"], timeout_s=10) == 0
        gc.collect()

    assert not [w for w in caught if issubclass(w.category, ResourceWarning)]


def test_process_control_reports_suspend_failure_and_clears_false_pause(monkeypatch):
    from dragontools.worker import process_control

    class Worker:
        def __init__(self):
            self._paused = True
            self._pause_ev = threading.Event()
            self._pause_ev.clear()
            self._current_process = object()
            self.logs = []

        def log(self, message, level="info"):
            self.logs.append((level, message))

    worker = Worker()
    monkeypatch.setattr(process_control, "suspend_process", lambda *args, **kwargs: False)

    ok = process_control.wait_while_paused(worker, threading.Lock())

    assert ok is False
    assert worker._paused is False
    assert worker._pause_ev.is_set()
    assert any("Pause konnte nicht sicher" in message for _level, message in worker.logs)


def test_postprocess_enablement_error_is_fail_closed():
    from dragontools.worker.workflow_output_commit import WorkflowOutputCommitCoordinator

    class BrokenPostProcess:
        def is_enabled(self):
            raise RuntimeError("broken config")

    class Logger:
        def __init__(self):
            self.messages = []

        def warn(self, message):
            self.messages.append(message)

    logger = Logger()
    service = WorkflowOutputCommitCoordinator(
        replace_service=object(),
        logger=logger,
        result_service=object(),
        sidecar_outputs=None,
        postprocess_outputs=None,
        postprocess_service=BrokenPostProcess(),
    )
    ctx = SimpleNamespace(final_output_path="out.mkv", output_path="out.mkv", input_path="in.mkv")

    assert service.start_postprocess(ctx) is False
    assert any("Statuspruefung fehlgeschlagen" in message for message in logger.messages)


def test_crash_guard_reports_marker_write_failure(tmp_path, monkeypatch, capfd):
    from dragontools.core import crash_guard

    state_file = tmp_path / "crash_state.json"
    monkeypatch.setattr(crash_guard, "_state_file", state_file)
    monkeypatch.setattr(
        crash_guard,
        "atomic_write_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )

    assert crash_guard.mark_activity("Test") is False
    captured = capfd.readouterr()
    assert "CrashGuard" in captured.err


def test_quality_tester_has_a_configurable_hard_timeout():
    from dragontools.core.timeout_settings import get_default

    assert get_default("quality_test_process") == 3600


def test_move_preflight_uses_public_collaborator_api():
    source = (PACKAGE_ROOT / "gui" / "move_preflight_controller.py").read_text(encoding="utf-8")
    assert "self._lifecycle._" not in source
    assert "self._requests._" not in source


def test_production_code_contains_no_runtime_assert_statements():
    import ast

    root = PACKAGE_ROOT
    offenders = []
    for path in root.rglob("*.py"):
        if "tests" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                offenders.append(f"{path}:{node.lineno}")
    assert offenders == []


def test_converter_runtime_builder_has_no_converter_thread_import():
    source = (PACKAGE_ROOT / "worker" / "converter_runtime_builder.py").read_text(encoding="utf-8")
    assert "import dragontools.worker.converter_thread" not in source


def test_process_lifecycle_crash_marker_includes_activity_file(monkeypatch):
    from dragontools.worker import tool_process_lifecycle

    calls = []
    monkeypatch.setattr(
        tool_process_lifecycle,
        "mark_activity",
        lambda stage, **kwargs: calls.append((stage, kwargs)) or True,
    )

    lifecycle = tool_process_lifecycle.ProcessLifecycle(
        command=["ffmpeg", "-i", "episode.mkv"],
        label="Trickplay ffmpeg",
        timeout_s=10,
        file_path=r"D:\\Media\\episode.mkv",
    )
    lifecycle.mark_starting()

    assert calls
    assert calls[0][1]["file_path"] == r"D:\\Media\\episode.mkv"
