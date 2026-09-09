from __future__ import annotations

import sys
import types
from types import SimpleNamespace


class _QtObject:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def __getattr__(self, _name):
        return _QtObject()

    def __call__(self, *args, **kwargs):
        return _QtObject()


class _QSettings:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def value(self, _key, default=None, type=None):
        return default


def _install_pyqt_stubs(monkeypatch) -> None:
    if "PyQt6" in sys.modules:
        return

    pyqt6 = types.ModuleType("PyQt6")
    qtcore = types.ModuleType("PyQt6.QtCore")
    qtgui = types.ModuleType("PyQt6.QtGui")
    qtwidgets = types.ModuleType("PyQt6.QtWidgets")

    qtcore.Qt = _QtObject()
    qtcore.QSettings = _QSettings
    qtcore.QTimer = _QtObject
    qtcore.QThread = _QtObject
    qtcore.pyqtSignal = lambda *args, **kwargs: _Signal()

    qtgui.QPixmap = _QtObject
    qtgui.QColor = _QtObject

    for name in [
        "QCheckBox",
        "QComboBox",
        "QGraphicsDropShadowEffect",
        "QGroupBox",
        "QHBoxLayout",
        "QLabel",
        "QPushButton",
        "QScrollArea",
        "QSpinBox",
        "QFrame",
        "QTextEdit",
        "QVBoxLayout",
        "QWidget",
        "QGridLayout",
        "QToolButton",
        "QDialog",
        "QDialogButtonBox",
        "QInputDialog",
        "QLineEdit",
        "QListWidget",
        "QListWidgetItem",
        "QMessageBox",
        "QRadioButton",
    ]:
        setattr(qtwidgets, name, _QtObject)

    monkeypatch.setitem(sys.modules, "PyQt6", pyqt6)
    monkeypatch.setitem(sys.modules, "PyQt6.QtCore", qtcore)
    monkeypatch.setitem(sys.modules, "PyQt6.QtGui", qtgui)
    monkeypatch.setitem(sys.modules, "PyQt6.QtWidgets", qtwidgets)


class _Signal:
    def __init__(self) -> None:
        self.slots = []

    def connect(self, slot) -> None:
        self.slots.append(slot)


class _Button:
    def __init__(self) -> None:
        self.enabled = None
        self.text = ""

    def setEnabled(self, value) -> None:
        self.enabled = bool(value)

    def setText(self, value) -> None:
        self.text = value


class _FileList:
    def __init__(self, paths: list[str]) -> None:
        self._paths = paths

    def get_paths(self) -> list[str]:
        return list(self._paths)


class _MoveThread:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        self.log_line = _Signal()
        self.request_user = _Signal()
        self.file_counted = _Signal()
        self.finished = _Signal()
        self._move_report_log = []
        self.ok_count = 0
        self.error_count = 0
        self.started = False

    def start(self) -> None:
        self.started = True


def _controller(monkeypatch):
    _install_pyqt_stubs(monkeypatch)

    move_module = types.ModuleType("dragontools.worker.move_thread")
    move_module.MoveThread = _MoveThread
    monkeypatch.setitem(sys.modules, "dragontools.worker.move_thread", move_module)

    layout_module = types.ModuleType("dragontools.gui.convert_widget_layout")
    layout_module.ConvertWidgetUI = object
    monkeypatch.setitem(sys.modules, "dragontools.gui.convert_widget_layout", layout_module)

    from dragontools.gui.conversion_session_state import ConversionSessionState
    from dragontools.gui.move_preflight_controller import MovePreflightController
    import dragontools.gui.move_preflight_controller as module

    monkeypatch.setattr(module, "MoveThread", _MoveThread)

    state = ConversionSessionState()
    state.thread = SimpleNamespace(isRunning=lambda: True, log_file_path="run.log")
    ui = SimpleNamespace(
        move_finished_btn=_Button(),
        pause_btn=_Button(),
        abort_btn=_Button(),
        file_list=_FileList(["input-a.mkv", "input-b.mkv"]),
    )
    queue_edit_calls: list[bool] = []
    start_enabled_calls: list[bool] = []
    refreshes: list[bool] = []

    controller = MovePreflightController(
        state=state,
        ui=ui,
        log=lambda *_args, **_kwargs: None,
        parent_widget=None,
        get_target_paths=lambda: {"tv": "", "anime": "", "film": ""},
        finalize_run=lambda *_args, **_kwargs: None,
        set_start_enabled=start_enabled_calls.append,
        set_queue_edit=queue_edit_calls.append,
        refresh_queue=lambda: refreshes.append(True),
    )
    return controller, state, ui, queue_edit_calls, start_enabled_calls, refreshes



def test_move_status_text_uses_shared_ui_helper(monkeypatch):
    controller, _state, ui, _queue_calls, _start_calls, _refreshes = _controller(monkeypatch)

    class _Item:
        def __init__(self) -> None:
            self.text = None

        def setText(self, value) -> None:
            self.text = value

    item = _Item()
    ui.file_list = SimpleNamespace(item_for_path=lambda path: item if path == "input-a.mkv" else None)

    controller.set_file_list_item_text("input-a.mkv", "📦 Verschoben  input-a.mkv")

    assert item.text == "📦 Verschoben  input-a.mkv"

def test_incremental_move_does_not_lock_queue_edit(monkeypatch):
    controller, state, ui, queue_edit_calls, _start_enabled_calls, refreshes = _controller(monkeypatch)

    controller.start_incremental_move(["finished-output.mkv"])

    assert state.incremental_move_active is True
    assert isinstance(state.move_thread, _MoveThread)
    assert state.move_thread.started is True
    assert ui.move_finished_btn.enabled is False
    assert queue_edit_calls == []
    assert refreshes


def test_incremental_move_finish_keeps_queue_edit_enabled(monkeypatch):
    controller, state, _ui, queue_edit_calls, start_enabled_calls, _refreshes = _controller(monkeypatch)
    controller.start_incremental_move(["finished-output.mkv"])

    controller.finish_incremental_move()

    assert state.incremental_move_active is False
    assert state.move_thread is None
    assert queue_edit_calls == [True]
    assert start_enabled_calls == [False]


def test_incremental_move_finish_uses_finished_thread_reference(monkeypatch):
    controller, state, _ui, queue_edit_calls, start_enabled_calls, _refreshes = _controller(monkeypatch)
    controller.set_file_list_item_text = lambda *_args, **_kwargs: None
    state.fertig.add("finished-output.mkv")
    controller.start_incremental_move(["finished-output.mkv"])
    finished_move_thread = state.move_thread
    finished_move_thread._move_report_log = [{
        "kind": "video",
        "ok": True,
        "source_path": "finished-output.mkv",
    }]
    finished_move_thread.ok_count = 1
    replacement_thread = SimpleNamespace(isRunning=lambda: True)
    state.move_thread = replacement_thread

    controller.finish_incremental_move(finished_move_thread)

    assert state.move_thread is replacement_thread
    assert state.incremental_move_active is False
    assert "finished-output.mkv" not in state.fertig
    assert finished_move_thread in state.retired_move_threads
    assert queue_edit_calls == [True]
    assert start_enabled_calls == [False]


def test_incremental_move_does_not_start_without_running_conversion(monkeypatch):
    controller, state, _ui, queue_edit_calls, start_enabled_calls, refreshes = _controller(monkeypatch)
    state.thread = SimpleNamespace(isRunning=lambda: False)

    controller.start_incremental_move(["finished-output.mkv"])

    assert state.move_thread is None
    assert state.incremental_move_active is False
    assert queue_edit_calls == []
    assert start_enabled_calls == []
    assert refreshes


def test_preflight_report_save_uses_rows_builder_and_logs(monkeypatch, tmp_path):
    controller, _state, _ui, _queue_calls, _start_calls, _refreshes = _controller(monkeypatch)
    logs: list[tuple] = []
    captured: dict = {}

    controller._log = lambda *args, **kwargs: logs.append(args)
    controller._preflight_rows_builder = lambda files, targets: [
        {
            "path": files[0],
            "severity": "ok",
            "status": "OK",
            "target": targets[files[0]],
        }
    ]

    import dragontools.core.preflight_report as report_module

    def fake_write(files, **kwargs):
        captured["files"] = files
        captured.update(kwargs)
        return tmp_path / "preflight.txt"

    monkeypatch.setattr(report_module, "write_preflight_report", fake_write)

    result = controller.save_report(
        ["input.mkv"],
        {"input.mkv": r"D:\Ziel"},
        {"tv": "", "anime": "", "film": r"D:\Filme"},
        title="Test-Preflight",
    )

    assert result == tmp_path / "preflight.txt"
    assert captured["files"] == ["input.mkv"]
    assert captured["rows"][0]["status"] == "OK"
    assert captured["planned_targets"] == {"input.mkv": r"D:\Ziel"}
    assert any("Preflight-Bericht gespeichert" in entry[0] for entry in logs)


def test_preflight_dialog_report_checkbox_controls_save_flag(monkeypatch):
    _install_pyqt_stubs(monkeypatch)

    from dragontools.gui.preflight_dialog import PreFlightDialog

    dlg = PreFlightDialog.__new__(PreFlightDialog)
    dlg._save_report_cb = SimpleNamespace(isChecked=lambda: True)

    assert dlg.should_save_report() is True

    dlg._save_report_cb = SimpleNamespace(isChecked=lambda: False)
    assert dlg.should_save_report() is False

    dlg._save_report_cb = None
    assert dlg.should_save_report() is False
