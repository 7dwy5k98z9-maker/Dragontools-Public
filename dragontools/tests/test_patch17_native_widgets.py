"""Exercise actual Qt utility widgets without starting external media tools."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt6.QtCore import Qt, QObject, pyqtSignal

# Capture native GUI/Qt classes before adjacent legacy tests install Qt stubs.
from dragontools.gui import iso_widget_runtime, audio_muxer_widget, merge_widget, mp4_remux_widget
from dragontools.gui.iso_widget import ISOWidget


@pytest.mark.parametrize('kind', ['audio', 'mp4', 'merge', 'iso'])
def test_active_utility_worker_cannot_be_replaced_by_programmatic_start(qtbot, monkeypatch, tmp_path, kind):
    module, cls, factory_name = {
        'audio': (audio_muxer_widget, audio_muxer_widget.AudioMuxerWidget, 'AudioMuxThread'),
        'mp4': (mp4_remux_widget, mp4_remux_widget.MP4RemuxWidget, 'MP4RemuxThread'),
        'merge': (merge_widget, merge_widget.MergeWidget, 'MergeThread'),
        'iso': (iso_widget_runtime, ISOWidget, 'ISOThread'),
    }[kind]
    widget = cls()
    qtbot.addWidget(widget)
    if kind == 'iso':
        widget.input_list.addItem(str(tmp_path / 'disc.iso'))
        widget.output_edit.setText(str(tmp_path))
        old = SimpleNamespace(isRunning=lambda: True)
        widget._scan_worker = old
    else:
        from PyQt6.QtWidgets import QListWidgetItem
        for name in ['a.mkv', 'b.mkv']:
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, str(tmp_path / name))
            widget.file_list.addItem(item)
        old = SimpleNamespace(isRunning=lambda: True)
        widget._worker = old
        if kind == 'merge':
            widget.output_edit.setText(str(tmp_path / 'output.mkv'))
    factory = Mock(return_value=Mock())
    monkeypatch.setattr(module, factory_name, factory)
    if kind == 'mp4':
        monkeypatch.setattr(module, 'load_subtitle_rules', lambda **kwargs: {})
    widget._start()
    factory.assert_not_called()
    assert old in widget.iter_shutdown_workers()


@pytest.mark.parametrize('physically_running', [False, True])
def test_audio_widget_start_error_retains_only_a_physically_running_worker(qtbot, monkeypatch, tmp_path, physically_running):
    widget = audio_muxer_widget.AudioMuxerWidget()
    qtbot.addWidget(widget)
    from PyQt6.QtWidgets import QListWidgetItem
    item = QListWidgetItem('source.mkv')
    item.setData(Qt.ItemDataRole.UserRole, str(tmp_path / 'source.mkv'))
    widget.file_list.addItem(item)
    worker = Mock()
    worker.isRunning.return_value = physically_running
    worker.start.side_effect = RuntimeError('start observer failed')
    monkeypatch.setattr(audio_muxer_widget, 'AudioMuxThread', Mock(return_value=worker))
    widget._start()
    assert widget.btn_start.isEnabled() is not physically_running
    assert (widget._worker is worker) is physically_running


def test_iso_fallback_selection_has_a_clear_native_label(qtbot):
    from dragontools.worker.iso_models import FFMPEG_FALLBACK_TITLE_ID
    widget = ISOWidget()
    qtbot.addWidget(widget)
    widget._analyzed_input_path = 'disc.iso'
    widget._on_scan_file_progress('disc.iso', 15, [
        {'id': FFMPEG_FALLBACK_TITLE_ID, 'name': 'FFmpeg-Fallback: Stream', 'size': 2048}])
    item = widget.title_list.item(0)
    assert 'FFmpeg-Fallback' in item.text() and 'Titel -1' not in item.text()
    item.setSelected(True)
    assert widget._collect_selected_titles() == {'disc.iso': [FFMPEG_FALLBACK_TITLE_ID]}


class _NativeUtilityWorker(QObject):
    log_line = pyqtSignal(str)
    progress_total = pyqtSignal(int)
    progress_file = pyqtSignal(str, int)
    progress = pyqtSignal(int)
    file_progress = pyqtSignal(str, int, object)
    file_result = pyqtSignal(str, bool, str)
    files_extracted = pyqtSignal(list)
    finished = pyqtSignal()
    def start(self):
        pass
    def isRunning(self):
        return False


@pytest.mark.parametrize('kind', ['audio', 'mp4', 'merge', 'iso'])
def test_reentrant_constructor_and_stale_native_signals_cannot_change_the_new_owner(qtbot, monkeypatch, tmp_path, kind):
    from PyQt6.QtWidgets import QListWidgetItem
    module, cls, factory_name = {
        'audio': (audio_muxer_widget, audio_muxer_widget.AudioMuxerWidget, 'AudioMuxThread'),
        'mp4': (mp4_remux_widget, mp4_remux_widget.MP4RemuxWidget, 'MP4RemuxThread'),
        'merge': (merge_widget, merge_widget.MergeWidget, 'MergeThread'),
        'iso': (iso_widget_runtime, ISOWidget, 'ISOThread'),
    }[kind]
    widget = cls()
    qtbot.addWidget(widget)
    if kind == 'iso':
        widget.input_list.addItem(str(tmp_path / 'disc.iso'))
        widget.output_edit.setText(str(tmp_path))
    else:
        for name in ['a.mkv', 'b.mkv']:
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, str(tmp_path / name))
            widget.file_list.addItem(item)
        if kind == 'merge':
            widget.output_edit.setText(str(tmp_path / 'out.mkv'))
    if kind == 'mp4':
        monkeypatch.setattr(module, 'load_subtitle_rules', lambda **kw: {})
    old = _NativeUtilityWorker()
    calls = []
    def construct(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            widget._start()
        return old
    monkeypatch.setattr(module, factory_name, construct)
    widget._start()
    assert len(calls) == 1
    current = _NativeUtilityWorker()
    widget._worker = current
    old.finished.emit()
    old.file_result.emit('old.mkv', False, 'STALE RESULT')
    old.log_line.emit('STALE LOG')
    assert widget._worker is current
    assert current in widget.iter_shutdown_workers()
    assert 'STALE' not in (widget.log.toPlainText() if kind == 'audio' else widget.log_edit.toPlainText())


def test_owned_callback_is_discarded_after_the_native_widget_is_destroyed(qapp):
    from PyQt6 import sip
    from dragontools.gui.utility_worker_start import connect_owned_signal
    widget = audio_muxer_widget.AudioMuxerWidget()
    worker = object()
    widget._worker = worker
    deliveries = []
    signal = SimpleNamespace(connect=lambda callback: deliveries.append(callback))
    callback = Mock()
    connect_owned_signal(widget, '_worker', worker, signal, callback)
    sip.delete(widget)
    deliveries[0]('late result')
    callback.assert_not_called()


def test_utility_construction_is_visible_to_shutdown_and_can_be_cancelled(qtbot, monkeypatch, tmp_path):
    from PyQt6.QtWidgets import QListWidgetItem
    widget = audio_muxer_widget.AudioMuxerWidget()
    qtbot.addWidget(widget)
    item = QListWidgetItem('source.mkv')
    item.setData(Qt.ItemDataRole.UserRole, str(tmp_path / 'source.mkv'))
    widget.file_list.addItem(item)
    worker = Mock()
    worker.isRunning.return_value = False
    seen = []
    def construct(**kwargs):
        seen.extend(widget.iter_shutdown_workers())
        for held in seen:
            held.request_abort('sofort')
        return worker
    monkeypatch.setattr(audio_muxer_widget, 'AudioMuxThread', construct)
    widget._start()
    assert seen and not any(held.isRunning() for held in seen)
    worker.start.assert_not_called()
    assert not widget.iter_shutdown_workers() and widget.btn_start.isEnabled()
