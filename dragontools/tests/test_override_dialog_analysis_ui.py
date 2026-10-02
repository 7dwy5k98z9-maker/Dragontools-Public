from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QObject, QTimer, pyqtSignal, QCoreApplication, QEvent
from PyQt6.QtWidgets import QApplication, QWidget, QDialog, QDialogButtonBox

from dragontools.gui import convert_widget_override_dialog as subject


@pytest.mark.parametrize('outcome', ['failed', 'empty', 'cancel'])
@pytest.mark.parametrize('batch', [False, True])
def test_real_dialog_analysis_result_and_cancel(monkeypatch, outcome, batch):
    app = QApplication.instance() or QApplication([])
    owner = QWidget()
    owner.settings = SimpleNamespace(organizationName=lambda: 'test', applicationName=lambda: 'test')
    monkeypatch.setattr('PyQt6.QtCore.QSettings', lambda *a: SimpleNamespace(
        value=lambda key, default=None, **kwargs: default))
    before = {'a': {'audio_mode':'custom','audio_tracks':[{'index':1,'mode':'drop'}],
                    'subtitle_mode':'custom','subtitle_tracks':[{'index':2,'keep':True}]},
              'b': {'audio_mode':'auto','encoder_profile':'other'}}
    owner._state = SimpleNamespace(file_overrides=deepcopy(before), thread=None, preflight_rows_by_path={})
    owner.tools = None
    owner.default_codec = 'h265'
    owner._guard_queue_edit_allowed = lambda *a: True
    owner._log = Mock()
    owner.log_message = Mock()
    owner.update_queue_label = Mock()
    monkeypatch.setattr(subject, 'install_persistent_window_geometry', lambda *a: None)
    monkeypatch.setattr(subject, 'EncoderOverrideDialogHelper', lambda *a, **k:
        SimpleNamespace(build_group=lambda *a: {}, persist_group=lambda *a: None))
    dialogs = []
    results = []
    class Dialog(subject._OverrideDialog):
        def __init__(self, *args):
            super().__init__(*args)
            dialogs.append(self)
    monkeypatch.setattr(subject, '_OverrideDialog', Dialog)
    class Loader(QObject):
        loaded = pyqtSignal(object, object, object)
        failed = pyqtSignal(str)
        finished = pyqtSignal()
        def __init__(self, path, tools, parent): super().__init__(parent)
        def start(self):
            if outcome == 'failed': self.failed.emit('simulated unreadable source')
            else: self.loaded.emit(None, [], [])
            dlg = dialogs[-1]
            button = dlg.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok)
            results.append(button.isEnabled())
            if outcome == 'cancel': dlg.reject()
            else: button.click()
            self.finished.emit()
        def isRunning(self): return False
        def abort(self): pass
    monkeypatch.setattr(subject, '_OverrideAnalyzeThread', Loader)
    helper = subject.ConvertWidgetOverrideDialogHelper(owner)
    original_audio = helper._build_audio_group
    original_sub = helper._build_subtitle_group
    widgets = {}
    def audio(*args):
        value = original_audio(*args)
        widgets['audio'] = value[0]
        return value
    def subtitles(*args):
        value = original_sub(*args)
        widgets['subtitles'] = value[0]
        return value
    helper._build_audio_group = audio
    helper._build_subtitle_group = subtitles
    helper.edit_override(['a','b'] if batch else 'a')
    assert results == [True]
    if outcome == 'failed':
        assert not widgets['audio'].isEnabled() and not widgets['subtitles'].isEnabled()
        for name in ['a','b'] if batch else ['a']:
            for key in ('audio_mode','audio_tracks','subtitle_mode','subtitle_tracks'):
                assert owner._state.file_overrides[name].get(key) == before[name].get(key)
    elif outcome == 'cancel':
        assert owner._state.file_overrides == before
        owner.update_queue_label.assert_not_called()
    else:
        assert widgets['audio'].isEnabled() and widgets['subtitles'].isEnabled()
        assert owner._state.file_overrides['a']['audio_tracks'] == []
        assert owner._state.file_overrides['a']['subtitle_tracks'] == []
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not owner.findChildren(QDialog)
    owner.close()
    owner.deleteLater()
    app.processEvents()
