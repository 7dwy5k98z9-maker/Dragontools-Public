from __future__ import annotations

import ast
import threading
from pathlib import Path
from types import SimpleNamespace


WORKER_DIR = Path(__file__).resolve().parents[1] / "worker"


def _class_and_method(filename: str, class_name: str, method_name: str):
    path = WORKER_DIR / filename
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    method = next(
        node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == method_name
    )
    return path, tree, cls, method


def test_converter_thread_is_bounded_qthread_facade():
    path, _tree, cls, run_method = _class_and_method(
        "converter_thread.py", "ConverterThread", "run"
    )

    assert cls.end_lineno - cls.lineno + 1 < 400
    assert run_method.end_lineno - run_method.lineno + 1 <= 20
    init_method = next(
        node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "__init__"
    )
    assert init_method.end_lineno - init_method.lineno + 1 <= 60
    init_self_attrs = {
        node.attr
        for node in ast.walk(init_method)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    }
    assert len(init_self_attrs) <= 25

    source = path.read_text(encoding="utf-8")
    assert "ConverterRuntimeBuilder" in source
    assert "ConverterRunLoop" in source
    assert "ConverterLifecycleService" in source
    assert "ConverterFileExecutor" in source
    assert "ConverterControlService" in source
    assert "ConverterJobState" in source
    assert "ConverterControlState" in source
    assert "ConverterSessionState" in source
    assert "build_static_converter_services" in source
    assert "settings_int(" not in source
    assert "settings_bool(" not in source
    assert "get_tool_paths(" not in source


def test_converter_refactor_services_have_bounded_responsibilities():
    limits = {
        "converter_runtime_builder.py": 280,
        "converter_run_loop.py": 190,
        "converter_lifecycle.py": 150,
        "converter_file_executor.py": 150,
        "converter_control.py": 180,
    }
    for filename, limit in limits.items():
        path = WORKER_DIR / filename
        assert path.is_file(), filename
        assert len(path.read_text(encoding="utf-8").splitlines()) < limit, filename


def test_runtime_builder_uses_explicit_workflow_composition_root():
    builder_source = (WORKER_DIR / "converter_runtime_builder.py").read_text(encoding="utf-8")
    factory_source = (WORKER_DIR / "workflow_factory.py").read_text(encoding="utf-8")
    workflow_source = (WORKER_DIR / "workflow_services.py").read_text(encoding="utf-8")

    assert "build_workflow_services(" in builder_source
    assert "services=services" in builder_source
    assert "session_state=worker._session_state" in builder_source
    assert "WorkflowPipelineExecutor(" in factory_source
    assert "DVPipelineExecutorAdapter(services.dv_pipeline, temp_state)" in factory_source
    assert "hdrplus_pipeline=services.hdrplus" in factory_source
    assert "worker." not in factory_source
    assert "__self__" not in workflow_source
    assert "._encoder_config" not in workflow_source
    assert "._hdrplus_helper" not in workflow_source


def test_run_loop_honors_abort_after_current_file(monkeypatch):
    import dragontools.worker.converter_run_loop as module

    monkeypatch.setattr(module, "quick_video_resolution", lambda *_args: None)
    monkeypatch.setattr(module, "mark_activity", lambda *_args, **_kwargs: None)

    class Signal:
        def __init__(self):
            self.values = []

        def emit(self, value):
            self.values.append(value)

    class Queue:
        def __init__(self):
            self.files = ["a.mkv", "b.mkv"]
            self.current_file = None
            self.done_files = []

        def next_file(self, _done_count):
            if not self.files:
                self.current_file = None
                return None
            self.current_file = self.files[0]
            return self.current_file, len(self.files) + len(self.done_files)

        def complete_current(self, path):
            assert self.current_file == path
            self.done_files.append(path)
            self.files.remove(path)
            self.current_file = None

        def total_after_processed(self, done_count):
            return done_count + len(self.files)

    queue = Queue()
    converted = []
    logs = []
    worker = SimpleNamespace(
        _runtime_state=SimpleNamespace(total_count=2, current_idx=0),
        log_file_path=None,
        _verbose_logger=SimpleNamespace(log_file=None),
        _suppress_session_header=True,
        _logger=SimpleNamespace(header=lambda **_kwargs: None),
        _log_gpu_list=[],
        _log_enc_name="cpu",
        codec="h265",
        crf=22,
        preset="medium",
        scale_mode="original",
        overwrite_original=False,
        strip_only=False,
        encoder_options={},
        file_overrides={},
        abort_requested=False,
        abort_type=None,
        _queue=queue,
        files=queue.files,
        _display_index_by_path={},
        _display_total=None,
        tools=SimpleNamespace(ffprobe="ffprobe"),
        progress=Signal(),
        wait_if_paused=lambda: None,
        log=lambda msg, level="info": logs.append((msg, level)),
    )

    def convert_file(path):
        converted.append(path)
        worker.abort_requested = True
        worker.abort_type = "nach_datei"
        return True

    worker.convert_file = convert_file

    module.ConverterRunLoop(worker).execute()

    assert converted == ["a.mkv"]
    assert queue.done_files == ["a.mkv"]
    assert queue.files == ["b.mkv"]
    assert any("Abbruch nach Datei" in msg for msg, _level in logs)


def test_lifecycle_open_file_recovery_excludes_completed_entries():
    from dragontools.worker.converter_lifecycle import ConverterLifecycleService

    queue = SimpleNamespace(
        current_file="B.mkv",
        files=["B.mkv", "C.mkv", "A.mkv"],
        done_files=["A.mkv"],
    )
    worker = SimpleNamespace(
        _files_lock=threading.Lock(),
        _queue=queue,
        _all_input_files=["A.mkv", "B.mkv", "C.mkv"],
    )

    result = ConverterLifecycleService(worker)._open_files_for_run_exception()

    assert result == ["B.mkv", "C.mkv"]


def test_control_abort_after_file_can_be_cleared_without_killing_process():
    from dragontools.worker.converter_control import ConverterControlService

    logs = []
    worker = SimpleNamespace(
        abort_requested=False,
        abort_type=None,
        _paused=False,
        log=lambda msg, level="info": logs.append((msg, level)),
    )
    worker.resume = lambda: None

    control = ConverterControlService(worker)
    control.request_abort("nach_datei")

    assert worker.abort_requested is True
    assert worker.abort_type == "nach_datei"
    assert control.clear_abort_request() is True
    assert worker.abort_requested is False
    assert worker.abort_type is None
    assert any("zurückgenommen" in msg for msg, _level in logs)


def test_control_immediate_abort_uses_existing_process_tree_termination(monkeypatch):
    import dragontools.worker.converter_control as module

    calls = []
    monkeypatch.setattr(
        module,
        "terminate_process_tree",
        lambda worker, lock, **kwargs: calls.append((worker, lock, kwargs)) or True,
    )
    lock = threading.Lock()
    worker = SimpleNamespace(
        abort_requested=False,
        abort_type=None,
        _paused=False,
        _lock=lock,
        log=lambda *_args, **_kwargs: None,
    )
    worker.resume = lambda: None

    module.ConverterControlService(worker).request_abort("sofort")

    assert worker.abort_requested is True
    assert worker.abort_type == "sofort"
    assert len(calls) == 1
    assert calls[0][1] is lock
    assert calls[0][2]["attr_name"] == "_current_process"


def test_control_pause_and_resume_keep_event_contract():
    from dragontools.worker.converter_control import ConverterControlService

    event = threading.Event()
    event.set()
    messages = []
    worker = SimpleNamespace(
        _paused=False,
        _pause_ev=event,
        _logger=SimpleNamespace(info=messages.append),
    )
    control = ConverterControlService(worker)

    control.pause()
    assert worker._paused is True
    assert event.is_set() is False

    control.resume()
    assert worker._paused is False
    assert event.is_set() is True
    assert len(messages) == 2


def test_converter_state_models_are_qt_independent_and_explicit():
    state_source = (WORKER_DIR / "converter_thread_state.py").read_text(encoding="utf-8")
    static_source = (WORKER_DIR / "converter_static_composition.py").read_text(encoding="utf-8")

    assert "PyQt" not in state_source
    assert "@dataclass(slots=True)\nclass ConverterJobState" in state_source
    assert "@dataclass(slots=True)\nclass ConverterControlState" in state_source
    assert "@dataclass(slots=True)\nclass ConverterSessionState" in state_source
    assert "@dataclass(slots=True)\nclass ConverterServiceRegistry" in state_source
    assert "subprocess.run(" not in static_source
    assert "Popen(" not in static_source


def test_converter_job_state_copies_mutable_config_maps():
    from dragontools.worker.converter_config import ConverterConfig
    from dragontools.worker.converter_thread_state import ConverterJobState

    config = ConverterConfig(
        codec="h265",
        crf=20,
        preset="medium",
        scale_mode="original",
        overwrite_original=False,
        encoder_options={"encoder": "cpu"},
        file_overrides={"a.mkv": {"crf": 18}},
        subtitle_rules={"schema_version": 4},
    )
    state = ConverterJobState.from_config(config)
    state.encoder_options["encoder"] = "nvenc"
    state.file_overrides["a.mkv"]["crf"] = 19
    state.subtitle_rules["schema_version"] = 999

    assert config.encoder_options["encoder"] == "cpu"
    # Nested override dictionaries intentionally retain historical shallow-copy semantics.
    assert config.file_overrides["a.mkv"]["crf"] == 19
    assert config.subtitle_rules["schema_version"] == 4
