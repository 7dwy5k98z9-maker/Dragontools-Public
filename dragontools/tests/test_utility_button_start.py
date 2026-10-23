"""Exercise actual Qt button signals through the shared utility start guard."""
from importlib import import_module

import pytest
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import QListWidgetItem, QPushButton, QWidget

from dragontools.gui.utility_worker_start import owned_utility_start


class FakeWorker(QObject):
    log_line = pyqtSignal(str)
    progress = pyqtSignal(int)
    progress_total = pyqtSignal(int)
    progress_file = pyqtSignal(str, int)
    file_progress = pyqtSignal(str, int, object)
    file_result = pyqtSignal(str, bool, str)
    files_extracted = pyqtSignal(list)
    finished = pyqtSignal()

    def __init__(self, **options):
        super().__init__()
        self.options = options
        self.started = False
        self.aborted = False

    def start(self):
        self.started = True

    def isRunning(self):
        return self.started and not self.aborted

    def request_abort(self):
        self.aborted = True

    def finish(self):
        self.started = False
        self.finished.emit()


@pytest.fixture
def iso(qtbot, tmp_path, monkeypatch):
    from dragontools.gui import iso_widget_runtime as runtime
    from dragontools.gui.iso_widget import ISOWidget
    workers = []
    def factory(**options):
        worker = FakeWorker(**options)
        workers.append(worker)
        return worker
    monkeypatch.setattr(runtime, 'ISOThread', factory)
    widget = ISOWidget()
    qtbot.addWidget(widget)
    source = str(tmp_path / 'The.Book.of.Eli.iso')
    widget._add_paths([source])
    widget.output_edit.setText(str(tmp_path))
    return widget, workers, source


@pytest.mark.parametrize('checkable', [False, True])
@pytest.mark.parametrize('action', ['analyze', 'extract'])
def test_iso_buttons_start_workers_with_real_clicked_boolean(iso, checkable, action):
    widget, workers, source = iso
    button = widget._btn_analyze if action == 'analyze' else widget._btn_start
    button.setCheckable(checkable)
    button.click()
    assert len(workers) == 1, widget.log_edit.toPlainText()
    worker = workers[0]
    assert worker.started
    assert worker.options['inputs'] == [source]
    assert bool(worker.options.get('scan_only')) == (action == 'analyze')
    assert not widget._btn_start.isEnabled() and widget._btn_abort.isEnabled()
    assert not widget._utility_start_claimed
    assert widget._utility_start_owner is None
    assert 'Start fehlgeschlagen' not in widget.log_edit.toPlainText()
    worker.finish()
    assert widget._worker is None and widget._scan_worker is None
    assert widget._btn_start.isEnabled() and not widget._btn_abort.isEnabled()


def test_iso_scan_selection_extraction_progress_abort_and_handoff(iso):
    widget, workers, source = iso
    widget._btn_analyze.click()
    assert len(workers) == 1, widget.log_edit.toPlainText()
    scan = workers[0]
    scan.file_progress.emit(source, 100, [{'id': 0, 'name': 'Film', 'duration': 7200, 'size': 1000000}])
    assert widget.title_list.count() == 1
    assert 'Film' in widget.title_list.item(0).text()
    scan.finish()
    widget.title_list.item(0).setSelected(True)
    widget.handoff_cb.setChecked(True)
    handoffs = []
    widget.handoff_requested.connect(handoffs.append)
    widget._btn_start.click()
    extraction = workers[1]
    assert extraction.options['selected_titles'] == {source: [0]}
    extraction.progress.emit(42)
    assert widget.progress_bar.value() == 42
    widget._btn_abort.click()
    assert extraction.aborted
    extraction.files_extracted.emit(['Film.mkv'])
    extraction.finish()
    assert handoffs == [['Film.mkv']]


def test_failed_iso_start_restores_controls_and_can_be_retried(iso, monkeypatch):
    from dragontools.gui import iso_widget_runtime as runtime
    widget, workers, _source = iso
    original = runtime.ISOThread
    def fail(**_options):
        raise RuntimeError('simulated constructor failure')
    monkeypatch.setattr(runtime, 'ISOThread', fail)
    widget._btn_analyze.click()
    assert 'simulated constructor failure' in widget.log_edit.toPlainText()
    assert widget._btn_analyze.isEnabled() and not widget._btn_abort.isEnabled()
    assert widget._scan_worker is None and widget._utility_start_owner is None
    monkeypatch.setattr(runtime, 'ISOThread', original)
    widget._btn_analyze.click()
    assert len(workers) == 1 and workers[0].started
    workers[0].finish()


def test_queued_iso_click_does_not_start_second_worker(iso):
    widget, workers, _source = iso
    widget._btn_analyze.click()
    assert len(workers) == 1, widget.log_edit.toPlainText()
    # Explicit emission models a queued click even though controls are disabled.
    widget._btn_start.clicked.emit(False)
    widget._btn_analyze.clicked.emit(False)
    assert len(workers) == 1
    assert widget._scan_worker is workers[0]
    workers[0].finish()


@pytest.mark.parametrize('tool', ['merge', 'merge_check', 'mp4', 'audio'])
def test_other_utility_buttons_reach_the_same_guard_without_argument_errors(qtbot, tmp_path, monkeypatch, tool):
    module_name, class_name, worker_name = {
        'merge': ('merge_widget', 'MergeWidget', 'MergeThread'),
        'merge_check': ('merge_widget', 'MergeWidget', 'MergeThread'),
        'mp4': ('mp4_remux_widget', 'MP4RemuxWidget', 'MP4RemuxThread'),
        'audio': ('audio_muxer_widget', 'AudioMuxerWidget', 'AudioMuxThread'),
    }[tool]
    module = import_module('dragontools.gui.' + module_name)
    workers = []
    def factory(**options):
        worker = FakeWorker(**options)
        workers.append(worker)
        return worker
    monkeypatch.setattr(module, worker_name, factory)
    monkeypatch.setattr(module.QMessageBox, 'warning', lambda *_a, **_k: pytest.fail('unexpected warning'))
    if tool == 'mp4':
        monkeypatch.setattr(module, 'load_subtitle_rules', lambda **_kw: {})
    widget = getattr(module, class_name)()
    qtbot.addWidget(widget)
    files = [str(tmp_path / 'a.mkv'), str(tmp_path / 'b.mkv')]
    for path in files:
        item = QListWidgetItem(path)
        item.setData(Qt.ItemDataRole.UserRole, path)
        widget.file_list.addItem(item)
    if tool.startswith('merge'):
        widget.output_edit.setText(str(tmp_path / 'out.mkv'))
        monkeypatch.setattr(widget, '_validate_output_path', lambda _path: True)
        button = widget._btn_check if tool == 'merge_check' else widget._btn_start
    else:
        button = widget.start_button if tool == 'mp4' else widget.btn_start
    button.click()
    assert len(workers) == 1
    assert workers[0].started and workers[0].options['files'] == files
    workers[0].finish()


def test_guard_keeps_parameterized_calls_and_returns_intact(qtbot):
    class Owner(QWidget):
        _worker = None

        @owned_utility_start('_worker')
        def execute(self, first, second, *, callback):
            return callback(first, second)

    owner = Owner()
    qtbot.addWidget(owner)
    assert owner.execute(3, 4, callback=lambda a, b: a + b) == 7
    assert not owner._utility_start_claimed and owner._utility_start_owner is None


def test_guard_preserves_checked_argument_when_slot_explicitly_accepts_it(qtbot):
    class Owner(QWidget):
        _worker = None

        @owned_utility_start('_worker')
        def execute(self, checked=False):
            self.checked = checked

    owner = Owner()
    qtbot.addWidget(owner)
    button = QPushButton()
    qtbot.addWidget(button)
    button.setCheckable(True)
    button.clicked.connect(owner.execute)
    button.click()
    assert owner.checked is True


def test_reentrant_no_argument_start_and_body_typeerror_are_not_retried(qtbot):
    class Owner(QWidget):
        _worker = None
        calls = 0

        def set_utility_running(self, _running):
            pass

        def _append_log(self, text):
            self.error = text

        @owned_utility_start('_worker')
        def execute(self):
            self.calls += 1
            self.execute()
            raise TypeError('actual body error')

    owner = Owner()
    qtbot.addWidget(owner)
    button = QPushButton()
    qtbot.addWidget(button)
    button.clicked.connect(owner.execute)
    button.click()
    assert owner.calls == 1
    assert 'actual body error' in owner.error
    assert not owner._utility_start_claimed and owner._utility_start_owner is None
