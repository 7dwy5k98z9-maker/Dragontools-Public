from __future__ import annotations

import sys
import types
from types import SimpleNamespace


class FakeSignal:
    def __init__(self) -> None:
        self.slots = []

    def connect(self, slot) -> None:
        self.slots.append(slot)

    def emit(self, *args) -> None:
        for slot in list(self.slots):
            slot(*args)


class FakeSignalDescriptor:
    def __set_name__(self, _owner, name: str) -> None:
        self.private_name = f"_{name}_signal"

    def __get__(self, instance, _owner):
        if instance is None:
            return self
        signal = getattr(instance, self.private_name, None)
        if signal is None:
            signal = FakeSignal()
            setattr(instance, self.private_name, signal)
        return signal


class FakeQObject:
    def __init__(self, *args, **kwargs) -> None:
        pass


class FakeLogger:
    def __init__(self) -> None:
        self.log_file = None
        self.lines: list[str] = []

    def header(self, **kwargs) -> None:
        self.lines.append(f"header:{kwargs.get('total_files')}")

    def info(self, text: str) -> None:
        self.lines.append(text)

    def warn(self, text: str) -> None:
        self.lines.append(text)

    def error(self, text: str) -> None:
        self.lines.append(text)


class FakeWorker:
    instances: list["FakeWorker"] = []

    def __init__(self, files, config, **kwargs) -> None:
        self.files = list(files)
        self.config = config
        self.kwargs = kwargs
        self._running = False
        self._paused = False
        self.abort_requested = False
        self.abort_type = None
        self._runtime_state = SimpleNamespace(total_count=len(self.files))
        self._replace_service = SimpleNamespace(blocked_move_inputs=set(), archiviert=0)
        self._sidecar_outputs = {}
        self._postprocess_outputs = {}
        self._failure_details = {}

        self.log_line = FakeSignal()
        self.event = FakeSignal()
        self.file_progress = FakeSignal()
        self.file_result = FakeSignal()
        self.progress = FakeSignal()
        self.finished = FakeSignal()
        FakeWorker.instances.append(self)

    def start(self) -> None:
        self._running = True

    def isRunning(self) -> bool:
        return self._running

    def add_file(self, path: str) -> bool:
        self.files.append(path)
        return True

    def remove_file(self, path: str):
        from dragontools.worker.worker_contracts import RemoveFileStatus

        if path in self.files:
            self.files.remove(path)
            return RemoveFileStatus.REMOVED
        return RemoveFileStatus.NOT_FOUND

    def is_current(self, path: str) -> bool:
        return False

    def reorder_waiting_files(self, new_order: list[str]) -> None:
        mine = set(self.files)
        self.files = [path for path in new_order if path in mine]

    def update_override(self, path: str, override: dict) -> bool:
        return path in self.files

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def request_abort(self, mode: str = "sofort") -> None:
        self.abort_requested = True
        self.abort_type = mode


def _install_parallel_fakes(monkeypatch):
    pyqt6 = types.ModuleType("PyQt6")
    qtcore = types.ModuleType("PyQt6.QtCore")
    qtcore.QObject = FakeQObject
    qtcore.QThread = FakeQObject
    qtcore.QSettings = lambda *_args, **_kwargs: None
    qtcore.pyqtSignal = lambda *_args, **_kwargs: FakeSignalDescriptor()
    monkeypatch.setitem(sys.modules, "PyQt6", pyqt6)
    monkeypatch.setitem(sys.modules, "PyQt6.QtCore", qtcore)

    import dragontools.worker.parallel_converter_thread as module

    FakeWorker.instances = []
    logger = FakeLogger()
    monkeypatch.setattr(module, "ConverterThread", FakeWorker)
    monkeypatch.setattr(module, "create_worker_logger", lambda **_kwargs: logger)
    monkeypatch.setattr(module, "QSettings", lambda *_args, **_kwargs: None)
    return module, logger


def _thread(module, files, jobs=2):
    from dragontools.worker.converter_config import ConverterConfig

    config = ConverterConfig(
        codec="h265",
        crf=23,
        preset="medium",
        scale_mode="original",
        overwrite_original=True,
        encoder_options={"encoder": "cpu"},
    )
    return module.ParallelConverterThread(
        files,
        config,
        parallel_jobs=jobs,
    )


def test_parallel_thread_starts_limited_workers_and_aggregates_progress(monkeypatch):
    module, logger = _install_parallel_fakes(monkeypatch)
    thread = _thread(module, ["a.mkv", "b.mkv", "c.mkv"], jobs=2)

    thread.start()

    assert len(FakeWorker.instances) == 2
    assert FakeWorker.instances[0].files == ["a.mkv"]
    assert FakeWorker.instances[1].files == ["b.mkv"]
    assert thread.active_file_count() == 2
    assert thread.display_position_for_path("b.mkv", fallback_idx=1, fallback_total=1) == (2, 3)
    assert any("Parallele Bearbeitung" in line for line in logger.lines)
    snapshot = thread.diagnostic_snapshot()
    assert snapshot["type"] == "parallel_converter"
    assert snapshot["active_count"] == 2
    assert snapshot["pending_files"] == ["c.mkv"]

    thread._on_child_file_progress("a.mkv", 50, None)
    assert thread.aggregate_progress_percent() == 16

    thread._on_child_file_result(FakeWorker.instances[0], "a.mkv", "a_out.mkv", "✅")
    assert thread.aggregate_progress_percent() == 33

    thread._on_child_finished(FakeWorker.instances[0])
    assert len(FakeWorker.instances) == 3
    assert FakeWorker.instances[2].files == ["c.mkv"]


def test_parallel_thread_delegates_pause_resume_and_abort(monkeypatch):
    module, _logger = _install_parallel_fakes(monkeypatch)
    thread = _thread(module, ["a.mkv", "b.mkv"], jobs=2)
    thread.start()

    thread.pause()
    assert all(worker._paused for worker in FakeWorker.instances)

    thread.resume()
    assert not any(worker._paused for worker in FakeWorker.instances)

    thread.request_abort("nach_datei")
    assert thread.abort_requested
    assert all(worker.abort_type == "nach_datei" for worker in FakeWorker.instances)

    assert thread.clear_abort_request() is True
    assert not thread.abort_requested
    assert all(not worker.abort_requested for worker in FakeWorker.instances)
    assert all(worker.abort_type is None for worker in FakeWorker.instances)


def test_parallel_thread_add_remove_and_reorder_queue(monkeypatch):
    module, _logger = _install_parallel_fakes(monkeypatch)
    thread = _thread(module, ["a.mkv", "b.mkv"], jobs=2)
    thread.start()

    assert thread.add_file("c.mkv") is True
    assert "c.mkv" in thread.files
    assert thread._pending_files == ["c.mkv"]

    thread.reorder_waiting_files(["c.mkv", "b.mkv", "a.mkv"])
    assert thread.files == ["c.mkv", "b.mkv", "a.mkv"]
    assert thread._pending_files == ["c.mkv"]

    from dragontools.worker.worker_contracts import RemoveFileStatus

    assert thread.remove_file("c.mkv") == RemoveFileStatus.REMOVED
    assert "c.mkv" not in thread.files


def test_parallel_thread_frees_slot_while_postprocessing_waits(monkeypatch):
    module, _logger = _install_parallel_fakes(monkeypatch)
    thread = _thread(module, ["a.mkv", "b.mkv", "c.mkv"], jobs=2)
    finished = []
    thread.finished.connect(lambda: finished.append(True))
    thread.start()

    first = FakeWorker.instances[0]
    thread._on_child_file_result(first, "a.mkv", "a_out.mkv", "🧩")

    assert first in thread._postprocessing_workers
    assert first not in thread._active_workers
    assert len(FakeWorker.instances) == 3
    assert FakeWorker.instances[2].files == ["c.mkv"]
    assert finished == []

    thread._on_child_file_result(first, "a.mkv", "a_out.mkv", "✅")
    thread._on_child_finished(first)

    assert first not in thread._postprocessing_workers


def test_parallel_thread_waits_for_terminal_postprocess_signal_before_finished(monkeypatch):
    module, _logger = _install_parallel_fakes(monkeypatch)
    thread = _thread(module, ["a.mkv"], jobs=1)
    finished = []
    thread.finished.connect(lambda: finished.append(True))
    thread.start()

    first = FakeWorker.instances[0]
    thread._on_child_file_result(first, "a.mkv", "a_out.mkv", "🧩")
    thread._on_child_finished(first)

    assert finished == []

    thread._on_child_file_result(first, "a.mkv", "a_out.mkv", "✅")

    assert finished == [True]


def test_parallel_thread_marks_unreported_child_finish_as_error(monkeypatch):
    module, logger = _install_parallel_fakes(monkeypatch)
    thread = _thread(module, ["a.mkv"], jobs=1)
    results = []
    finished = []
    thread.file_result.connect(lambda *args: results.append(args))
    thread.finished.connect(lambda: finished.append(True))
    thread.start()

    child = FakeWorker.instances[0]
    child._running = False
    thread._on_child_finished(child)

    assert results == [("a.mkv", "a.mkv", "❌")]
    assert thread.fehlgeschlagen == 1
    assert finished == [True]
    assert any("Worker beendet ohne Dateiergebnis" in line for line in logger.lines)
