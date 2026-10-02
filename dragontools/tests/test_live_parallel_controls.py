from types import SimpleNamespace
from unittest.mock import Mock

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QWidget, QVBoxLayout

from dragontools.gui.convert_widget_parallel_controls import ParallelWorkerControl
from dragontools.worker import parallel_converter_thread as parallel_module
from dragontools.core.settings_storage import (
    SET_KEY_PARALLEL_CPU_JOBS, SET_KEY_PARALLEL_GPU_JOBS,
    SET_KEY_PARALLEL_DEFAULTS_MIGRATED,
)


def owner_widget(qtbot, tmp_path):
    owner = QWidget()
    qtbot.addWidget(owner)
    owner.settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    owner.settings.setValue(SET_KEY_PARALLEL_DEFAULTS_MIGRATED, True)
    owner.settings.setValue(SET_KEY_PARALLEL_CPU_JOBS, 1)
    owner.settings.setValue(SET_KEY_PARALLEL_GPU_JOBS, 2)
    owner._state = SimpleNamespace(thread=None, move_thread=None, start_reserved=False)
    owner._enc_settings = SimpleNamespace(_active_encoder=lambda: "cpu")
    owner._log = Mock()
    return owner


@pytest.mark.parametrize("encoder,key,other", [
    ("cpu", SET_KEY_PARALLEL_CPU_JOBS, SET_KEY_PARALLEL_GPU_JOBS),
    ("nvenc", SET_KEY_PARALLEL_GPU_JOBS, SET_KEY_PARALLEL_CPU_JOBS),
])
def test_live_spin_updates_current_run_and_matching_encoder_default(qtbot, tmp_path, encoder, key, other):
    owner = owner_widget(qtbot, tmp_path)
    other_value = owner.settings.value(other, type=int)
    worker = SimpleNamespace(
        parallel_jobs=2, encoder_options={"encoder": encoder},
        isRunning=lambda: True, encode_active_count=lambda: 2,
    )
    changed = []

    def set_limit(value):
        changed.append(value)
        worker.parallel_jobs = value
        return value

    worker.set_parallel_jobs = set_limit
    owner._state.thread = worker
    control = ParallelWorkerControl(owner)
    control.refresh()
    assert control.spin.value() == 2
    control.spin.setValue(1)
    assert changed == [1]
    assert control.active_label.text() == "2 aktiv"
    assert owner.settings.value(key, type=int) == 1
    assert owner.settings.value(other, type=int) == other_value
    control.spin.setValue(3)
    assert changed == [1, 3]
    assert owner.settings.value(key, type=int) == 3


def test_idle_defaults_follow_encoder_and_serial_modes_disable_control(qtbot, tmp_path):
    owner = owner_widget(qtbot, tmp_path)
    control = ParallelWorkerControl(owner)
    control.refresh()
    assert control.spin.value() == 1
    owner._enc_settings._active_encoder = lambda: "nvenc"
    control.refresh()
    assert control.spin.value() == 2
    control.spin.setValue(3)
    assert owner.settings.value(SET_KEY_PARALLEL_GPU_JOBS, type=int) == 3
    owner._state.thread = SimpleNamespace(isRunning=lambda: True, encoder_options={})
    control.refresh()
    assert not control.spin.isEnabled()
    owner._state.thread = None
    owner._state.move_thread = SimpleNamespace(isRunning=lambda: True)
    control.refresh()
    assert not control.spin.isEnabled()
    owner._state.move_thread = None
    control.refresh()
    assert control.spin.isEnabled()


def test_all_quick_switches_stay_in_one_scrollable_line(qtbot, tmp_path, monkeypatch):
    from dragontools.gui.convert_widget_layout_runtime import ConvertWidgetLayoutRuntimeMixin
    from dragontools.gui.convert_widget_quick_settings import QUICK_TOGGLE_SPECS
    from dragontools.gui import rules_dialog_storage

    owner = owner_widget(qtbot, tmp_path)
    monkeypatch.setattr(rules_dialog_storage, "_load", lambda _name: {})
    builder = ConvertWidgetLayoutRuntimeMixin()
    builder.w, builder.settings = owner, owner.settings
    builder._build_file_list_section(QVBoxLayout(owner))
    owner.resize(2200, 300)
    owner.show()
    qtbot.waitUntil(lambda: owner.quick_toggle_scroll.viewport().width() > 1500)
    checkboxes = [getattr(owner, spec.attr_name) for spec in QUICK_TOGGLE_SPECS]
    assert len(checkboxes) == 10
    assert {checkbox.geometry().center().y() for checkbox in checkboxes} == {checkboxes[0].geometry().center().y()}
    initial_height = owner.quick_toggle_scroll.height()
    owner.resize(1100, 300)
    qtbot.waitUntil(lambda: owner.quick_toggle_scroll.horizontalScrollBar().maximum() > 0)
    assert owner.minimumSizeHint().width() < 1100
    assert owner.quick_toggle_scroll.height() == initial_height
    assert owner.quick_toggle_scroll.verticalScrollBar().maximum() == 0
    bar = owner.quick_toggle_scroll.horizontalScrollBar()
    bar.setValue(bar.maximum())
    owner.nfo_quick_cb.click()
    owner.trickplay_quick_cb.click()
    assert owner.settings.value("postprocess/nfo/enabled", type=bool)
    assert owner.settings.value("postprocess/trickplay/enabled", type=bool)


def test_live_limit_with_real_qthreads_and_queued_completion(qtbot, monkeypatch):
    import threading
    from PyQt6.QtCore import QThread, pyqtSignal
    module = parallel_module
    from dragontools.worker.converter_config import ConverterConfig

    class GatedWorker(QThread):
        log_line = pyqtSignal(str)
        worker_event = pyqtSignal(object)
        file_progress = pyqtSignal(str, int, object)
        file_result = pyqtSignal(str, str, str)
        progress = pyqtSignal(int)
        instances = []

        def __init__(self, files, config, *, parent=None, **kwargs):
            super().__init__(parent)
            self.files = list(files)
            self.allow_finish = threading.Event()
            self.started_work = threading.Event()
            self._runtime_state = SimpleNamespace(total_count=len(files))
            self._replace_service = SimpleNamespace(blocked_move_inputs=set(), archiviert=0)
            self._sidecar_outputs, self._postprocess_outputs, self._failure_details = {}, {}, {}
            self.instances.append(self)

        def run(self):
            self.started_work.set()
            self.file_progress.emit(self.files[0], 10, None)
            self.allow_finish.wait(5)
            self.file_result.emit(self.files[0], self.files[0] + ".out", "✅")

    monkeypatch.setattr(module, "ConverterThread", GatedWorker)
    monkeypatch.setattr(module, "worker_settings_snapshot", lambda: {})
    monkeypatch.setattr(module, "create_worker_logger", lambda **kwargs: Mock(log_file=None))

    def gpu_context(self):
        self._log_gpu_list, self._log_enc_name = [], "cpu"

    monkeypatch.setattr(module.ParallelConverterThread, "_initialize_gpu_log_context", gpu_context)
    config = ConverterConfig(codec="h265", crf=23, preset="medium", scale_mode="original", overwrite_original=False)
    thread = module.ParallelConverterThread(["a.mkv", "b.mkv", "c.mkv", "d.mkv"], config, parallel_jobs=2)
    finished = []
    thread.finished.connect(lambda: finished.append(True))
    try:
        thread.start()
        qtbot.waitUntil(lambda: len(GatedWorker.instances) == 2 and all(w.started_work.is_set() for w in GatedWorker.instances))
        first, second = GatedWorker.instances
        thread.set_parallel_jobs(1)
        assert first.isRunning() and second.isRunning()
        first.allow_finish.set()
        qtbot.waitUntil(lambda: thread.encode_active_count() == 1)
        assert len(GatedWorker.instances) == 2
        thread.set_parallel_jobs(3)
        qtbot.waitUntil(lambda: len(GatedWorker.instances) == 4 and all(w.started_work.is_set() for w in GatedWorker.instances))
        assert thread.encode_active_count() == 3
        for worker in GatedWorker.instances:
            worker.allow_finish.set()
        qtbot.waitUntil(lambda: not thread.isRunning())
        assert finished == [True]
        assert thread._terminal_inputs == {"a.mkv", "b.mkv", "c.mkv", "d.mkv"}
    finally:
        for worker in GatedWorker.instances:
            worker.allow_finish.set()
        for worker in GatedWorker.instances:
            worker.wait(6000)
