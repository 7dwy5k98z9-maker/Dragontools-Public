from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace

from dragontools.core.callback_dispatch import invoke_callback
from dragontools.core import json_io
from dragontools.core.release_validation import _check_build_environment, _check_ci_workflow
from dragontools.worker.move_batch_executor import MoveProgressTracker
from dragontools.worker.parallel_converter_state import ParallelResultState
from dragontools.worker.worker_result_service import WorkerConversionResultService


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKER_DIR = PROJECT_ROOT / "dragontools" / "worker"


class FakeQtSignal:
    """Models the PyQt contract that triggered the production TypeError."""

    def __init__(self) -> None:
        self.emissions: list[tuple] = []

    def __call__(self, *_args, **_kwargs):
        raise TypeError("native Qt signal is not callable")

    def emit(self, *args) -> None:
        self.emissions.append(tuple(args))


def test_signal_safe_callback_prefers_emit_over_direct_signal_call():
    signal = FakeQtSignal()

    invoke_callback(signal, "payload", 7)

    assert signal.emissions == [("payload", 7)]


def test_worker_result_service_accepts_native_signal_objects_directly():
    event_signal = FakeQtSignal()
    progress_signal = FakeQtSignal()
    result_signal = FakeQtSignal()
    service = WorkerConversionResultService(
        logger=SimpleNamespace(),
        runtime_state=SimpleNamespace(),
        overwrite_original=False,
        event_emit=event_signal,
        file_progress_emit=progress_signal,
        file_result_emit=result_signal,
        log=lambda *_args: None,
    )

    service.emit_file_progress("in.mkv", 42, 12.5)
    service.emit_file_result("in.mkv", "out.mkv", "✅")

    assert progress_signal.emissions == [("in.mkv", 42, 12.5)]
    assert result_signal.emissions == [("in.mkv", "out.mkv", "✅")]
    assert len(event_signal.emissions) == 2


def test_move_progress_tracker_accepts_native_signal_objects_directly(monkeypatch):
    progress_signal = FakeQtSignal()
    eta_signal = FakeQtSignal()
    times = iter((100.0, 101.0))
    monkeypatch.setattr("dragontools.worker.move_batch_executor.time.time", lambda: next(times))
    tracker = MoveProgressTracker(
        100,
        emit_progress=progress_signal,
        emit_eta=eta_signal,
    )

    tracker.update(25)

    assert progress_signal.emissions == [(25,)]
    assert len(eta_signal.emissions) == 1
    assert eta_signal.emissions[0][0] >= 0.0


def test_parallel_result_state_reads_refactored_converter_session_maps():
    child = SimpleNamespace(
        _session_state=SimpleNamespace(
            sidecar_outputs={"in.mkv": ["in.nfo", "in.trickplay"]},
            postprocess_outputs={"in.mkv": [{"kind": "trickplay", "status": "ok"}]},
            failure_details={"in.mkv": {"message": "detail"}},
        )
    )
    state = ParallelResultState()

    state.sync_from_child(child, "in.mkv")

    assert state.sidecar_outputs["in.mkv"] == ["in.nfo", "in.trickplay"]
    assert state.postprocess_outputs["in.mkv"][0]["kind"] == "trickplay"
    assert state.failure_details["in.mkv"]["message"] == "detail"


def test_converter_thread_restores_refactored_state_bridges():
    path = WORKER_DIR / "converter_thread.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ConverterThread")
    property_names = {
        node.name
        for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(isinstance(dec, ast.Name) and dec.id == "property" for dec in node.decorator_list)
    }

    assert {"_sidecar_outputs", "_postprocess_outputs", "_failure_details", "_replace_service"} <= property_names
    source = path.read_text(encoding="utf-8")
    assert "return self._session_state.sidecar_outputs" in source
    assert "return self._session_state.postprocess_outputs" in source
    assert "return self._session_state.failure_details" in source


def test_conversion_result_uses_nested_session_sidecars_after_refactor(monkeypatch):
    from dragontools.gui.conversion_result_service import ConversionResultService
    from dragontools.gui.conversion_session_state import ConversionSessionState

    class UI:
        file_list = object()

    input_path = "source.mkv"
    output_path = "converted.mkv"
    state = ConversionSessionState()
    state.thread = SimpleNamespace(
        _session_state=SimpleNamespace(
            sidecar_outputs={input_path: ["converted.nfo", "converted.trickplay"]},
            postprocess_outputs={input_path: [{"kind": "trickplay", "status": "ok"}]},
            failure_details={},
        ),
        _replace_service=SimpleNamespace(blocked_move_inputs=set()),
    )
    service = ConversionResultService(
        state=state,
        ui=UI(),
        log=lambda *_args, **_kwargs: None,
        start_move=lambda *_args, **_kwargs: None,
        set_start_enabled=lambda *_args: None,
        set_queue_edit=lambda *_args: None,
        refresh_queue=lambda: None,
        clear=lambda: None,
        confirm_shutdown=lambda: None,
    )
    monkeypatch.setattr(service, "_set_file_list_item_text", lambda *_args: None)

    service.on_file_result(input_path, output_path, "✅")

    assert state.sidecar_outputs_by_video[output_path] == ["converted.nfo", "converted.trickplay"]
    assert state.postprocess_outputs_by_input[input_path][0]["kind"] == "trickplay"
    assert state.run_results[input_path]["sidecars"] == ["converted.nfo", "converted.trickplay"]


def test_atomic_json_replace_retries_transient_windows_lock(tmp_path, monkeypatch):
    path = tmp_path / "crash_state.json"
    real_replace = json_io.os.replace
    calls = []

    def flaky_replace(source, target):
        calls.append((source, target))
        if len(calls) <= 2:
            exc = OSError("temporarily locked")
            exc.winerror = 5
            raise exc
        return real_replace(source, target)

    monkeypatch.setattr(json_io.os, "replace", flaky_replace)
    monkeypatch.setattr(json_io.time, "sleep", lambda _seconds: None)

    json_io.atomic_write_json(path, {"active": True})

    assert json.loads(path.read_text(encoding="utf-8")) == {"active": True}
    assert len(calls) == 3


def test_ci_validator_requires_explicit_cache_dependency_path(tmp_path):
    workflow = tmp_path / ".github" / "workflows" / "tests.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "\n".join(
            (
                "DRAGONTOOLS_REQUIRE_QT_TESTS",
                "QT_QPA_PLATFORM",
                "requirements-test.txt",
                "not dv_hdr_integration",
                "ruff check",
                "--select E9,F821,F822,F823",
                "DRAGONTOOLS_REQUIRE_DV_HDR_INTEGRATION",
                "self-hosted",
                "dragontools-media",
            )
        ),
        encoding="utf-8",
    )

    result = _check_ci_workflow(tmp_path)

    assert result.status == "error"
    assert "cache-dependency-path:" in result.detail


def test_build_validator_requires_defusedxml_in_build_script(tmp_path):
    (tmp_path / "requirements-runtime.txt").write_text(
        "PyQt6>=6\ncryptography>=42\ndefusedxml>=0.7.1\n", encoding="utf-8"
    )
    (tmp_path / "requirements-optional.txt").write_text(
        "numpy>=1\nopencv-python-headless>=4\n", encoding="utf-8"
    )
    (tmp_path / "requirements-build.txt").write_text(
        "-r requirements-runtime.txt\n-r requirements-optional.txt\nPyInstaller>=6\npyinstaller-hooks-contrib>=2025\n",
        encoding="utf-8",
    )
    (tmp_path / "build_v9.bat").write_text(
        "python -c \"import PyInstaller, PyQt6, cryptography\"\n", encoding="utf-8"
    )

    result = _check_build_environment(tmp_path)

    assert result.status == "error"
    assert "defusedxml" in result.detail


def test_current_ci_and_build_contracts_pass():
    assert _check_ci_workflow(PROJECT_ROOT).status == "ok"
    assert _check_build_environment(PROJECT_ROOT).status == "ok"


def test_critical_qt_connections_do_not_install_injected_signal_objects_as_slots():
    launcher = (WORKER_DIR / "parallel_worker_launcher.py").read_text(encoding="utf-8")
    conversion_lifecycle = (
        PROJECT_ROOT / "dragontools" / "gui" / "conversion_worker_lifecycle.py"
    ).read_text(encoding="utf-8")
    regular_move = (
        PROJECT_ROOT / "dragontools" / "gui" / "move_regular_lifecycle.py"
    ).read_text(encoding="utf-8")
    incremental_move = (
        PROJECT_ROOT / "dragontools" / "gui" / "move_incremental_lifecycle.py"
    ).read_text(encoding="utf-8")

    assert ".connect(log_emit)" not in launcher
    assert ".connect(event_emit)" not in launcher
    assert ".connect(relay_crop_decision)" not in launcher
    assert ".connect(on_file_progress)" not in launcher
    assert ".connect(total_progress_slot)" not in conversion_lifecycle
    assert ".log_line.connect(self._log)" not in regular_move
    assert ".request_user.connect(self._on_move_req)" not in regular_move
    assert ".log_line.connect(self._log)" not in incremental_move
    assert ".request_user.connect(self._on_move_req)" not in incremental_move
