"""Real Qt lifecycle checks and application-wide ownership boundaries."""
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

from PyQt6.QtCore import QThread, pyqtSignal, QSettings
from PyQt6.QtWidgets import QWidget

from dragontools.worker import parallel_converter_thread as parallel


def test_close_rechecks_workers_registered_during_wait(qtbot, monkeypatch):
    from dragontools.gui import main_window_shutdown as module
    window = QWidget()
    qtbot.addWidget(window)
    late = SimpleNamespace(isRunning=lambda: True, objectName=lambda: "late-worker",
                           requestInterruption=Mock(), wait=lambda _: False)
    held = []
    def finish_first(_timeout):
        first.running = False
        held.append(late)
        return True
    first = SimpleNamespace(running=True, isRunning=lambda: first.running,
                            requestInterruption=Mock(), wait=finish_first)
    held.append(first)
    monkeypatch.setattr(module, "application_worker_sources", lambda _: [
        SimpleNamespace(iter_shutdown_workers=lambda: tuple(held))])
    for name in ("stop_watch_folder_controller", "stop_metadata_action_thread", "stop_jellyfin_workers"):
        monkeypatch.setattr(module, name, lambda *args, **kwargs: True)
    warning = Mock()
    monkeypatch.setattr(module.QMessageBox, "warning", warning)
    assert not module.prepare_main_window_close(window, timeout_ms=0)
    late.requestInterruption.assert_called_once()
    assert "late-worker" in warning.call_args.args[2]


def _native_parallel(monkeypatch, files, *, release_on_abort=True):
    from dragontools.worker.converter_config import ConverterConfig
    class Child(QThread):
        log_line = pyqtSignal(str)
        worker_event = pyqtSignal(object)
        file_progress = pyqtSignal(str, int, object)
        file_result = pyqtSignal(str, str, str)
        progress = pyqtSignal(int)
        instances = []

        def __init__(self, files, config, *, parent=None, **kwargs):
            super().__init__(parent)
            self.files = list(files)
            self.started_work = Event()
            self.release = Event()
            self.abort_requested = False
            self._replace_service = SimpleNamespace(blocked_move_inputs=set(), archiviert=0)
            self._sidecar_outputs, self._postprocess_outputs, self._failure_details = {}, {}, {}
            self.instances.append(self)

        def request_abort(self, mode="sofort"):
            self.abort_requested = True
            if release_on_abort:
                self.release.set()

        def run(self):
            self.started_work.set()
            self.release.wait(5)
            self.file_result.emit(self.files[0], self.files[0], "⚠️" if self.abort_requested else "✅")

    monkeypatch.setattr(parallel, "ConverterThread", Child)
    monkeypatch.setattr(parallel, "create_worker_logger", lambda **kw: Mock(log_file=None))
    monkeypatch.setattr(parallel, "worker_settings_snapshot", lambda: {})
    monkeypatch.setattr(parallel.ParallelConverterThread, "_initialize_gpu_log_context",
        lambda self: (setattr(self, "_log_gpu_list", []), setattr(self, "_log_enc_name", "cpu")))
    config = ConverterConfig("h265", 23, "medium", "original", False)
    parent = parallel.ParallelConverterThread(files, config, parallel_jobs=2)
    return parent, Child


def _cleanup(parent, child_type, qtbot):
    for child in child_type.instances:
        child.release.set()
    for child in child_type.instances:
        assert child.wait(6000)
    qtbot.waitUntil(lambda: not parent.isRunning(), timeout=6000)


def test_native_parallel_shutdown_waits_for_children_and_terminal_delivery(qtbot, monkeypatch):
    from dragontools.gui.application_shutdown import shutdown_workers
    parent, children = _native_parallel(monkeypatch, ["a.mkv", "b.mkv", "c.mkv"])
    finished = []
    parent.finished.connect(lambda: finished.append(True))
    try:
        parent.start()
        qtbot.waitUntil(lambda: len(children.instances) == 2 and all(c.started_work.is_set() for c in children.instances))
        result = shutdown_workers([parent], timeout_ms=1500)
        assert result.ok
        assert not parent.isRunning()
        assert all(not c.isRunning() and c.abort_requested for c in children.instances)
        assert len(children.instances) == 2  # The waiting third source never starts after abort.
        assert finished == [True]
        qtbot.wait(20)
        assert finished == [True]
    finally:
        _cleanup(parent, children, qtbot)


def test_native_parallel_timeout_keeps_live_children_owned(qtbot, monkeypatch):
    from dragontools.gui.application_shutdown import shutdown_workers
    parent, children = _native_parallel(monkeypatch, ["a.mkv", "b.mkv"], release_on_abort=False)
    try:
        parent.start()
        qtbot.waitUntil(lambda: len(children.instances) == 2 and all(c.started_work.is_set() for c in children.instances))
        assert not shutdown_workers([parent], timeout_ms=10).ok
        assert parent.isRunning()
        assert all(c in parent._registry.workers and c.isRunning() for c in children.instances)
    finally:
        _cleanup(parent, children, qtbot)


def test_restart_guard_includes_workers_outside_loaded_tabs(qtbot, monkeypatch):
    from dragontools.gui import windows_restart_guard as module
    from dragontools.gui import application_worker_sources as sources
    window = QWidget()
    qtbot.addWidget(window)
    window._tab_widgets = {}
    worker = SimpleNamespace(isRunning=lambda: True, objectName=lambda: "source-probe")
    monkeypatch.setattr(sources, "active_source_visual_workers", lambda: (worker,))
    guard = module.WindowsRestartGuard(window)
    try:
        assert "source-probe" in guard._active_worker_names()
    finally:
        guard._timer.stop()
        guard.release()


def test_restart_rechecks_active_workers_after_modal_allow(qtbot, monkeypatch):
    from dragontools.gui import windows_restart_guard as module
    window = QWidget()
    qtbot.addWidget(window)
    guard = module.WindowsRestartGuard(window)
    active = []
    monkeypatch.setattr(guard, "_active_worker_names", lambda: tuple(active))
    monkeypatch.setattr(module, "user_initiated_shutdown_allowed", lambda: False)
    monkeypatch.setattr(guard, "_show_block_notice", lambda _: None)
    def answer(_):
        active.append("conversion-started-during-dialog")
        return module.ACTION_ALLOW
    monkeypatch.setattr(guard, "_ask_user", answer)
    manager = SimpleNamespace(allowsInteraction=lambda: True, cancel=Mock())
    try:
        guard.handle_commit_data_request(manager)
        manager.cancel.assert_called_once()
    finally:
        guard._timer.stop()
        guard.release()


def test_restart_guard_install_is_idempotent(qtbot):
    from dragontools.gui.windows_restart_guard import install_windows_restart_guard
    window = QWidget()
    qtbot.addWidget(window)
    first = install_windows_restart_guard(window)
    second = install_windows_restart_guard(window)
    try:
        assert first is second
    finally:
        first._timer.stop()
        second._timer.stop()
        first.release()
        second.release()


def test_main_close_uses_one_budget_for_all_background_services(monkeypatch):
    from dragontools.gui import main_window_shutdown as module
    stamp, budgets = [10.0], []
    monkeypatch.setattr(module.time, "monotonic", lambda: stamp[0])
    def wait(kind, budget):
        budgets.append((kind, budget))
        stamp[0] += 0.040
        return True
    monkeypatch.setattr(module, "stop_watch_folder_controller",
        lambda _, timeout_ms=8000: wait("watch", timeout_ms))
    monkeypatch.setattr(module, "shutdown_loaded_widgets",
        lambda _, timeout_ms: (wait("widgets", timeout_ms), SimpleNamespace(ok=True))[1])
    monkeypatch.setattr(module, "stop_metadata_action_thread",
        lambda _, timeout_ms: wait("metadata", timeout_ms))
    monkeypatch.setattr(module, "stop_jellyfin_workers",
        lambda timeout_ms: wait("jellyfin", timeout_ms))
    assert module.prepare_main_window_close(SimpleNamespace(_tab_widgets={}), timeout_ms=100)
    assert budgets[0] == ("watch", 0)
    assert all(value <= 60 for _, value in budgets[1:])
    assert budgets[-1][1] == 0


def test_watch_controller_rejects_old_scan_and_changed_settings(qapp, tmp_path, monkeypatch):
    from dragontools.gui import watch_folder_controller as module
    from dragontools.core.watch_folder import WatchFolderRule, WatchFolderCandidate
    from dragontools.tests.test_parallel_converter_thread import FakeSignal
    class Scan:
        def __init__(self, *args, **kwargs):
            self.completed, self.failed, self.finished = FakeSignal(), FakeSignal(), FakeSignal()
        def start(self): pass
        def isRunning(self): return False
    monkeypatch.setattr(module, "_WatchScanThread", Scan)
    controller = module.WatchFolderController(
        settings=QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat),
        enqueue_callback=Mock(return_value=[]),
    )
    controller._rules = [WatchFolderRule("rule", "watch", str(tmp_path))]
    candidate = WatchFolderCandidate("rule", "episode.mkv", "1", "h265", "", False)
    try:
        controller._start_scan(manual=True)
        first = controller._thread
        controller._start_scan(manual=True)
        second = controller._thread
        first.completed.emit([candidate])
        controller._enqueue_callback.assert_not_called()
        controller.refresh_settings()
        second.completed.emit([candidate])
        controller._enqueue_callback.assert_not_called()
    finally:
        controller._thread = None
        controller.stop(timeout_ms=0)


def test_watch_bridge_reuses_existing_controller():
    from dragontools.gui.watch_folder_main_window_bridge import start_watch_folder_controller
    existing = SimpleNamespace(refresh_settings=Mock())
    window = SimpleNamespace(_watch_folder_controller=existing)
    start_watch_folder_controller(window)
    assert window._watch_folder_controller is existing
    existing.refresh_settings.assert_called_once()


def test_watch_cannot_take_source_queued_in_other_codec_tab(monkeypatch):
    from dragontools.gui.watch_folder_main_window_bridge import enqueue_watch_folder_files
    queued = Mock(return_value=[r"C:\Watch\Episode.mkv"])
    converter = SimpleNamespace(enqueue_watch_folder_files=queued)
    manual = SimpleNamespace(file_list=SimpleNamespace(get_paths=lambda: [r"c:\watch\EPISODE.MKV"]))
    window = SimpleNamespace(_tab_widgets={"av1": converter, "h265": manual})
    assert enqueue_watch_folder_files(window, codec="av1", paths=[r"C:\Watch\Episode.mkv"]) == []
    queued.assert_not_called()


def test_close_discovery_exception_refuses_close_without_escape(monkeypatch):
    from dragontools.gui import main_window_shutdown as module
    monkeypatch.setattr(module.QMessageBox, "warning", lambda *a: None)
    def broken(*args, **kwargs):
        raise RuntimeError("watch stop status unknown")
    monkeypatch.setattr(module, "stop_watch_folder_controller", broken)
    assert not module.prepare_main_window_close(SimpleNamespace(_tab_widgets={}), timeout_ms=0)


def test_native_started_child_is_retained_after_start_observer_exception(qtbot, monkeypatch):
    from dragontools.gui.application_shutdown import shutdown_workers
    parent, children = _native_parallel(monkeypatch, ["a.mkv"])
    original_start = children.start
    def launch(self):
        original_start(self)
        assert self.started_work.wait(1)
        raise RuntimeError("observer failed after native QThread started")
    monkeypatch.setattr(children, "start", launch)
    try:
        parent.start()
        assert children.instances[0].isRunning()
        assert children.instances[0] in parent._registry.workers
        assert parent.isRunning()
        assert shutdown_workers([parent], timeout_ms=1500).ok
        assert not children.instances[0].isRunning()
    finally:
        _cleanup(parent, children, qtbot)
