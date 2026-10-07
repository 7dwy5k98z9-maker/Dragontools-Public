"""The requested context-menu pause affects one owned converter child only."""
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock
import sys
import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMenu, QWidget
import pytest

from dragontools.worker import parallel_converter_thread as parallel
from dragontools.tests.test_parallel_converter_thread import FakeWorker, FakeLogger, _thread


def test_resume_failure_still_resumes_and_closes_remaining_owned_handles():
    from dragontools.core.owned_process_pause import resume_handles
    kernel = Mock()
    kernel.WaitForSingleObject.return_value = 258
    kernel.CloseHandle.return_value = True
    native = Mock()
    native.NtResumeProcess.side_effect = [OSError("first resume failed"), 0]
    assert not resume_handles(kernel, native, [101, 102])
    assert [call.args[0] for call in native.NtResumeProcess.call_args_list] == [101, 102]
    assert [call.args[0] for call in kernel.CloseHandle.call_args_list] == [101, 102]


def test_suspend_failure_closes_new_handle_and_rolls_back_previous_member(monkeypatch):
    from dragontools.core import owned_process_pause as module
    kernel, native = Mock(), Mock()
    kernel.WaitForSingleObject.return_value = 258
    kernel.CloseHandle.return_value = True
    native.NtSuspendProcess.side_effect = [0, OSError("second suspend failed")]
    native.NtResumeProcess.return_value = 0
    monkeypatch.setattr(module, "job_process_ids", lambda *_: [1, 2])
    monkeypatch.setattr(module, "open_owned_member", lambda _kernel, _job, pid: 100 + pid)
    with pytest.raises(OSError, match="second suspend failed"):
        module.suspend_job_members(kernel, native, 900)
    assert [call.args[0] for call in kernel.CloseHandle.call_args_list] == [102, 101]
    native.NtResumeProcess.assert_called_once_with(101)
    kernel.TerminateJobObject.assert_not_called()


def test_failed_pause_rollback_terminates_only_the_owned_job(monkeypatch):
    from dragontools.core import owned_process_pause as module
    kernel, native = Mock(), Mock()
    kernel.WaitForSingleObject.return_value = 258
    kernel.CloseHandle.return_value = True
    native.NtSuspendProcess.side_effect = [0, 1]
    native.NtResumeProcess.return_value = 1
    monkeypatch.setattr(module, "job_process_ids", lambda *_: [1, 2])
    monkeypatch.setattr(module, "open_owned_member", lambda _kernel, _job, pid: 100 + pid)
    with pytest.raises(OSError, match="konnte nicht pausiert"):
        module.suspend_job_members(kernel, native, 900)
    kernel.TerminateJobObject.assert_called_once_with(900, 1)


def test_resume_api_failure_preserves_handles_for_owned_job_cleanup(monkeypatch):
    from threading import RLock
    from dragontools.core import owned_process_pause as module
    proc = SimpleNamespace(_dragontools_job_lock=RLock(), _dragontools_job=900,
                           _dragontools_pause_handles=[101, 102])
    monkeypatch.setattr(module, "windows_pause_api", Mock(side_effect=OSError("API unavailable")))
    with pytest.raises(OSError, match="API unavailable"):
        module.resume_owned_process_tree(proc)
    assert proc._dragontools_pause_handles == [101, 102]
    kernel = Mock()
    module.close_owned_pause_handles(proc, kernel)
    assert [call.args[0] for call in kernel.CloseHandle.call_args_list] == [101, 102]


def test_reused_process_id_outside_owned_job_is_never_suspended():
    from dragontools.core.owned_process_pause import open_owned_member
    kernel = Mock()
    kernel.OpenProcess.return_value = 101
    kernel.WaitForSingleObject.return_value = 258
    # IsProcessInJob succeeds while its BOOL output remains false.
    kernel.IsProcessInJob.return_value = True
    assert open_owned_member(kernel, 900, 1) is None
    kernel.CloseHandle.assert_called_once_with(101)


def _running(monkeypatch):
    module = parallel
    FakeWorker.instances = []
    monkeypatch.setattr(module, "ConverterThread", FakeWorker)
    monkeypatch.setattr(module, "create_worker_logger", lambda **kw: FakeLogger())
    monkeypatch.setattr(module, "worker_settings_snapshot", lambda: {})
    monkeypatch.setattr(module.ParallelConverterThread, "_initialize_gpu_log_context",
        lambda self: (setattr(self, "_log_gpu_list", []), setattr(self, "_log_enc_name", "cpu")))
    first, second, waiting = r"C:\Media\A.mkv", r"C:\Media\B.mkv", r"C:\Media\C.mkv"
    parent = _thread(module, [first, second, waiting], jobs=2)
    parent.start()
    return parent, first, second, waiting


def test_individual_pause_and_resume_use_windows_source_identity(monkeypatch):
    parent, a, b, _ = _running(monkeypatch)
    first, second = FakeWorker.instances
    assert parent.set_file_paused(a.lower(), True)
    assert parent.file_pause_state(a) is True
    assert first._paused and not second._paused
    assert not parent.is_paused
    assert parent.set_file_paused(a, False)
    assert parent.file_pause_state(a) is False
    assert not first._paused and not second._paused
    assert parent.file_pause_state(b) is False


def test_global_resume_preserves_individual_pause(monkeypatch):
    parent, a, b, _ = _running(monkeypatch)
    first, second = FakeWorker.instances
    assert parent.set_file_paused(a, True)
    parent.pause()
    assert first._paused and second._paused
    assert not parent.set_file_paused(a, False)
    parent.resume()
    assert first._paused and not second._paused
    assert parent.file_pause_state(a) is True and parent.file_pause_state(b) is False
    assert parent.set_file_paused(a, False)
    assert not first._paused


def test_individual_pause_does_not_free_an_encode_slot(monkeypatch):
    parent, a, _, waiting = _running(monkeypatch)
    assert parent.set_file_paused(a, True)
    assert len(FakeWorker.instances) == 2
    assert parent._pending_files == [waiting]
    assert parent.encode_active_count() == 2


def test_abort_releases_individual_pause_before_stopping_all_children(monkeypatch):
    parent, a, _, _ = _running(monkeypatch)
    assert parent.set_file_paused(a, True)
    parent.request_abort()
    assert all(c.abort_requested and not c._paused for c in FakeWorker.instances)
    assert not parent.set_file_paused(a, True)


@pytest.mark.parametrize("state", ["waiting", "terminal", "unknown", "stopped"])
def test_pause_rejects_sources_without_an_active_owner(monkeypatch, state):
    parent, a, _, waiting = _running(monkeypatch)
    path = {"waiting": waiting, "terminal": a, "unknown": "foreign.mkv", "stopped": a}[state]
    if state == "terminal":
        parent._on_child_file_result(FakeWorker.instances[0], a, a, "✅")
    if state == "stopped":
        FakeWorker.instances[0]._running = False
    assert parent.file_pause_state(path) is None
    assert not parent.set_file_paused(path, True)
    assert all(not c._paused for c in FakeWorker.instances)


def test_stale_child_control_token_cannot_pause_new_owner(monkeypatch):
    from dragontools.core.path_syntax import path_compare_key
    parent, a, _, _ = _running(monkeypatch)
    token = parent.file_control_token(a)
    replacement = FakeWorker([a], FakeWorker.instances[0].config)
    replacement.start()
    parent._assigned[path_compare_key(a)] = replacement
    assert not parent.set_file_paused(a, True, expected_worker=token)
    assert not replacement._paused


def test_native_menu_action_pauses_and_resumes_only_the_clicked_file(qtbot, monkeypatch):
    from dragontools.gui.file_worker_pause import add_file_worker_pause_action
    parent, a, _, _ = _running(monkeypatch)
    menu = QMenu()
    refresh = Mock()
    assert add_file_worker_pause_action(menu, a, worker_provider=lambda: parent, refresh=refresh)
    pause = menu.actions()[0]
    assert "Worker pausieren" in pause.text()
    pause.trigger()
    assert FakeWorker.instances[0]._paused and not FakeWorker.instances[1]._paused
    refresh.assert_called_once()
    menu.clear()
    assert add_file_worker_pause_action(menu, a, worker_provider=lambda: parent, refresh=refresh)
    assert "Worker fortsetzen" in menu.actions()[0].text()
    menu.actions()[0].trigger()
    assert not FakeWorker.instances[0]._paused


def test_context_action_rechecks_parent_after_run_restart(qtbot, monkeypatch):
    from dragontools.gui.file_worker_pause import add_file_worker_pause_action
    parent, a, _, _ = _running(monkeypatch)
    current = [parent]
    menu = QMenu()
    assert add_file_worker_pause_action(menu, a, worker_provider=lambda: current[0], refresh=lambda: None)
    replacement = _thread(parallel, [a, "other.mkv"], jobs=2)
    replacement.start()
    current[0] = replacement
    menu.actions()[0].trigger()
    assert all(not c._paused for c in FakeWorker.instances)


def test_context_action_does_not_offer_resume_under_global_pause(qtbot, monkeypatch):
    from dragontools.gui.file_worker_pause import add_file_worker_pause_action
    parent, a, _, _ = _running(monkeypatch)
    parent.pause()
    menu = QMenu()
    assert add_file_worker_pause_action(menu, a, worker_provider=lambda: parent, refresh=lambda: None)
    assert not menu.actions()[0].isEnabled()
    assert "Gesamt" in menu.actions()[0].toolTip()


def test_converter_list_context_menu_contains_real_pause_action(qtbot, monkeypatch):
    from dragontools.gui.convert_widget_queue_context_actions import ConvertWidgetQueueContextActionsMixin
    from dragontools.gui.convert_widget_file_queue import FileListWidget
    parent, a, _, _ = _running(monkeypatch)
    owner = QWidget()
    qtbot.addWidget(owner)
    rows = FileListWidget(owner)
    rows.add_path(a)
    rows.resize(600, 200)
    rows.show()
    owner._ui = SimpleNamespace(file_list=rows)
    owner._state = SimpleNamespace(thread=parent, file_overrides={})
    owner._controller = SimpleNamespace(is_file_active=lambda _: True, active_worker=lambda: parent)
    owner._context_selected_paths = lambda path: [path]
    owner._is_queue_blocking_move_active = lambda: False
    owner._refresh_queue_window = Mock()
    owner._log = Mock()
    def pick(menu, _):
        action = next((a for a in menu.actions() if "Worker pausieren" in a.text()), None)
        assert action is not None
        action.trigger()
    monkeypatch.setattr(QMenu, "exec", pick)
    pos = rows.visualItemRect(rows.item(0)).center()
    ConvertWidgetQueueContextActionsMixin._ctx_menu(owner, pos)
    assert FakeWorker.instances[0]._paused and not FakeWorker.instances[1]._paused


def test_separate_queue_window_offers_file_worker_pause(qtbot, monkeypatch):
    from dragontools.gui.convert_queue_window import ConvertQueueWindow
    from dragontools.gui.convert_widget_file_queue import FileListWidget
    parent, a, _, _ = _running(monkeypatch)
    source = FileListWidget()
    qtbot.addWidget(source)
    source.add_path(a)
    window = ConvertQueueWindow(None, default_codec="h265", source_list=source,
        is_queue_blocking_move_active=lambda: False, active_worker=lambda: parent,
        apply_queue_order=lambda _: None, toggle_pause=lambda: None, abort=lambda: None, on_closed=lambda: None)
    qtbot.addWidget(window)
    window.show()
    assert window.file_list.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
    def pick(menu, _):
        action = next(a for a in menu.actions() if "Worker pausieren" in a.text())
        action.trigger()
    monkeypatch.setattr(QMenu, "exec", pick)
    window.file_list.customContextMenuRequested.emit(window.file_list.visualItemRect(window.file_list.item(0)).center())
    assert FakeWorker.instances[0]._paused and not FakeWorker.instances[1]._paused


def test_native_threads_one_pauses_while_other_continues(qtbot, monkeypatch):
    from PyQt6.QtCore import QThread, pyqtSignal
    from dragontools.worker.converter_config import ConverterConfig
    class Child(QThread):
        log_line, worker_event = pyqtSignal(str), pyqtSignal(object)
        file_progress, file_result = pyqtSignal(str, int, object), pyqtSignal(str, str, str)
        progress = pyqtSignal(int)
        instances = []
        def __init__(self, files, config, *, parent=None, **kw):
            super().__init__(parent)
            self.files, self._paused, self.ticks = list(files), False, 0
            self.gate, self.stop = Event(), Event()
            self.gate.set()
            self._replace_service = SimpleNamespace(blocked_move_inputs=set(), archiviert=0)
            self.instances.append(self)
        @property
        def is_paused(self): return self._paused
        def pause(self): self._paused = True; self.gate.clear()
        def resume(self): self._paused = False; self.gate.set()
        def request_abort(self, mode="sofort"): self.stop.set(); self.gate.set()
        def run(self):
            while not self.stop.is_set():
                if self.gate.wait(0.005):
                    self.ticks += 1
                    self.stop.wait(0.005)
            self.file_result.emit(self.files[0], self.files[0], "⚠️")
    monkeypatch.setattr(parallel, "ConverterThread", Child)
    monkeypatch.setattr(parallel, "create_worker_logger", lambda **kw: Mock(log_file=None))
    monkeypatch.setattr(parallel, "worker_settings_snapshot", lambda: {})
    monkeypatch.setattr(parallel.ParallelConverterThread, "_initialize_gpu_log_context",
        lambda self: (setattr(self, "_log_gpu_list", []), setattr(self, "_log_enc_name", "cpu")))
    parent = parallel.ParallelConverterThread(["a.mkv", "b.mkv"],
        ConverterConfig("h265", 23, "medium", "original", False), parallel_jobs=2)
    try:
        parent.start()
        qtbot.waitUntil(lambda: len(Child.instances) == 2 and all(c.ticks >= 3 for c in Child.instances))
        first, second = Child.instances
        assert parent.set_file_paused("a.mkv", True)
        qtbot.wait(20)
        first_ticks, second_ticks = first.ticks, second.ticks
        qtbot.wait(50)
        assert first.ticks == first_ticks
        assert second.ticks > second_ticks
        assert parent.set_file_paused("a.mkv", False)
        qtbot.waitUntil(lambda: first.ticks > first_ticks)
        parent.request_abort()
        assert parent.wait(1500)
    finally:
        for child in Child.instances:
            child.request_abort()
            assert child.wait(6000)
        qtbot.waitUntil(lambda: not parent.isRunning())


@pytest.mark.skipif(os.name != "nt", reason="Native Windows suspension contract")
def test_native_windows_owned_process_pause_does_not_stop_other_process(qtbot, monkeypatch, tmp_path):
    from PyQt6.QtCore import QThread, pyqtSignal
    from dragontools.worker.converter_config import ConverterConfig
    from dragontools.worker.converter_thread_state import ConverterControlState
    from dragontools.worker.converter_control import ConverterControlService
    from dragontools.worker.tool_runner import run_tool
    from dragontools.worker import process_control
    monkeypatch.setattr("dragontools.worker.tool_process_lifecycle.mark_activity", lambda *a, **kw: None)
    class Child(QThread):
        log_line, worker_event = pyqtSignal(str), pyqtSignal(object)
        file_progress, file_result = pyqtSignal(str, int, object), pyqtSignal(str, str, str)
        progress = pyqtSignal(int)
        instances = []
        def __init__(self, files, config, *, parent=None, shared_logger=None):
            super().__init__(parent)
            self.files, self._control_state, self._logger = list(files), ConverterControlState(), shared_logger
            self.control = ConverterControlService(self, self._control_state)
            self.counter = tmp_path / (self.files[0] + " Ü counter.bin")
            self._replace_service = SimpleNamespace(blocked_move_inputs=set(), archiviert=0)
            self.result = None
            self.instances.append(self)
        @property
        def is_paused(self): return self._control_state.paused
        @property
        def abort_requested(self): return self._control_state.abort_requested
        @property
        def abort_type(self): return self._control_state.abort_type
        def pause(self): self.control.pause()
        def resume(self): self.control.resume()
        def request_abort(self, mode="sofort"): self.control.request_abort(mode)
        def log(self, *args): pass
        def run(self):
            code = "import sys,time\nf=open(sys.argv[1],'ab',buffering=0)\nwhile True:\n f.write(b'x');time.sleep(0.005)"
            self.result = run_tool([sys.executable, "-u", "-c", code, str(self.counter)],
                worker=self, abort_on_request=True, timeout_s=8)
            self.file_result.emit(self.files[0], self.files[0], "⚠️" if self.result.aborted else "❌")
    monkeypatch.setattr(parallel, "ConverterThread", Child)
    monkeypatch.setattr(parallel, "create_worker_logger", lambda **kw: Mock(log_file=None))
    monkeypatch.setattr(parallel, "worker_settings_snapshot", lambda: {})
    monkeypatch.setattr(parallel.ParallelConverterThread, "_initialize_gpu_log_context",
        lambda self: (setattr(self, "_log_gpu_list", []), setattr(self, "_log_enc_name", "cpu")))
    parent = parallel.ParallelConverterThread(["a.mkv", "b.mkv"],
        ConverterConfig("h265", 23, "medium", "original", False), parallel_jobs=2)
    original_suspend = process_control.suspend_process
    suspended = Event()
    pid = [None]
    def suspend(proc, **kwargs):
        ok = original_suspend(proc, **kwargs)
        if ok and proc is not None and proc.pid == pid[0]:
            suspended.set()
        return ok
    monkeypatch.setattr(process_control, "suspend_process", suspend)
    try:
        parent.start()
        qtbot.waitUntil(lambda: len(Child.instances) == 2 and all(c.counter.exists() and c.counter.stat().st_size >= 3 for c in Child.instances), timeout=5000)
        first, second = Child.instances
        pid[0] = first._control_state.current_process.pid
        assert parent.set_file_paused("a.mkv", True)
        qtbot.waitUntil(suspended.is_set, timeout=3000)
        first_size, second_size = first.counter.stat().st_size, second.counter.stat().st_size
        qtbot.wait(100)
        assert first.counter.stat().st_size == first_size
        assert second.counter.stat().st_size > second_size
        assert parent.set_file_paused("a.mkv", False)
        qtbot.waitUntil(lambda: first.counter.stat().st_size > first_size)
        parent.request_abort()
        assert parent.wait(3000)
        assert all(c.result.aborted and not c.result.ok for c in Child.instances)
        assert all(c._control_state.current_process is None for c in Child.instances)
    finally:
        for child in Child.instances:
            child.request_abort()
            assert child.wait(6000)
        qtbot.waitUntil(lambda: not parent.isRunning(), timeout=6000)
