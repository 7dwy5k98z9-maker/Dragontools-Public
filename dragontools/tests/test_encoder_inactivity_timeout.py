from __future__ import annotations

import importlib
import sys
import threading
from types import ModuleType


class _FakeWorker:
    def __init__(self):
        self._lock = threading.Lock()
        self._current_process = None
        self._paused = False
        self.abort_requested = False
        self.abort_type = None
        self.progress = []
        self.logs = []
        self._last_stderr = ""

    def wait_if_paused(self):
        return None

    def emit_file_progress(self, path, pct, eta_s):
        self.progress.append((path, pct, eta_s))

    def log(self, message, level="info"):
        self.logs.append((level, message))


def _install_qt_core_stub(monkeypatch):
    qt_pkg = ModuleType("PyQt6")
    qt_core = ModuleType("PyQt6.QtCore")

    class _QThread:
        def __init__(self, parent=None):
            self._parent = parent

    class _Signal:
        def emit(self, *args, **kwargs):
            return None

    def _pyqt_signal(*args, **kwargs):
        return _Signal()

    qt_core.QThread = _QThread
    qt_core.pyqtSignal = _pyqt_signal
    qt_pkg.QtCore = qt_core
    monkeypatch.setitem(sys.modules, "PyQt6", qt_pkg)
    monkeypatch.setitem(sys.modules, "PyQt6.QtCore", qt_core)
    sys.modules.pop("dragontools.worker.base_worker", None)
    sys.modules.pop("dragontools.worker.converter_progress", None)
    worker_pkg = sys.modules.get("dragontools.worker")
    if worker_pkg is not None and hasattr(worker_pkg, "converter_progress"):
        delattr(worker_pkg, "converter_progress")


def _load_converter_progress(monkeypatch):
    _install_qt_core_stub(monkeypatch)
    return importlib.import_module("dragontools.worker.converter_progress")


def test_ffmpeg_inactivity_timeout_allows_active_progress(monkeypatch, tmp_path):
    converter_progress = _load_converter_progress(monkeypatch)

    monkeypatch.setattr(converter_progress, "get_timeout", lambda key: 2.5)
    worker = _FakeWorker()
    helper = converter_progress.ConverterProgressHelper(worker)
    code = (
        "import sys, time\n"
        "for i in range(4):\n"
        "    print(f'out_time_ms={(i + 1) * 250000}', flush=True)\n"
        "    time.sleep(0.35)\n"
        "print('progress=end', flush=True)\n"
    )

    rc = helper.run_p(
        [sys.executable, "-c", code],
        str(tmp_path / "active.mkv"),
        1_000,
        label="Test-Encode",
    )

    assert rc == 0
    assert any(pct == 100 for _path, pct, _eta in worker.progress)
    assert not any("Keine ffmpeg-Rückmeldung" in msg for _level, msg in worker.logs)


def test_ffmpeg_inactivity_timeout_aborts_silent_process(monkeypatch, tmp_path):
    converter_progress = _load_converter_progress(monkeypatch)

    monkeypatch.setattr(converter_progress, "get_timeout", lambda key: 1)
    worker = _FakeWorker()
    helper = converter_progress.ConverterProgressHelper(worker)

    rc = helper.run_p(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        str(tmp_path / "silent.mkv"),
        1_000,
        label="Test-Encode",
    )

    assert rc == 124
    assert any("Keine ffmpeg-Rückmeldung" in msg for _level, msg in worker.logs)


def test_explicit_disabled_timeout_does_not_fall_back_to_general(monkeypatch, tmp_path):
    converter_progress = _load_converter_progress(monkeypatch)

    monkeypatch.setattr(converter_progress, "get_timeout", lambda key: 1)
    worker = _FakeWorker()
    helper = converter_progress.ConverterProgressHelper(worker)

    rc = helper.run_p(
        [sys.executable, "-c", "import time; time.sleep(1.4)"],
        str(tmp_path / "disabled.mkv"),
        1_000,
        timeout_s=None,
        label="Test-Encode",
    )

    assert rc == 0
    assert not any("Keine ffmpeg-Rückmeldung" in msg for _level, msg in worker.logs)


def test_run_capture_times_out_silent_tool_process(monkeypatch):
    converter_progress = _load_converter_progress(monkeypatch)

    worker = _FakeWorker()
    helper = converter_progress.ConverterProgressHelper(worker)

    rc, stdout, stderr = helper.run_capture(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        timeout_s=1,
        label="Test-Tool",
    )

    assert rc == 124
    assert stdout == ""
    assert stderr == ""
    assert any("Timeout" in msg for _level, msg in worker.logs)
