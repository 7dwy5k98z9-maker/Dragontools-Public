from pathlib import Path
from types import SimpleNamespace
import os
import struct
import subprocess
import sys

import pytest
pytest.importorskip('PyQt6')
from PyQt6.QtCore import QCoreApplication, QEvent, QSettings, QTimer, Qt
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtWidgets import QApplication, QDialog, QMainWindow, QTabWidget, QTextEdit, QWidget


@pytest.fixture
def app():
    application = QApplication.instance() or QApplication([])
    yield application
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()


def tabs_host(tmp_path):
    from dragontools.gui.main_window_tabs import MainWindowTabsMixin
    class Host(MainWindowTabsMixin, QMainWindow):
        pass
    host = Host()
    host.tabs = QTabWidget(host)
    host.setCentralWidget(host.tabs)
    host._settings = QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat)
    host._tab_widgets = {}
    host._closed_tabs = []
    host._tab_defs = [('h265', 'H265'), ('av1', 'AV1'), ('iso', 'ISO')]
    for key, label in host._tab_defs:
        widget = QWidget()
        index = host.tabs.addTab(widget, label)
        host.tabs.tabBar().setTabData(index, key)
        host._tab_widgets[key] = widget
    return host


def tab_keys(host):
    return [host.tabs.tabBar().tabData(i) for i in range(host.tabs.count())]


def test_reopening_already_visible_tab_cannot_duplicate_tab_identity(app, tmp_path):
    host = tabs_host(tmp_path)
    host._on_tab_close(1)
    host._reopen_tab('av1', 1)
    assert tab_keys(host).count('av1') == 1
    host.tabs.tabBar().moveTab(1, 2)
    before = tab_keys(host)
    host._reopen_last_tab()
    assert tab_keys(host).count('av1') == 1
    assert host.tabs.count() == 3
    assert tab_keys(host) == before
    host.deleteLater()


def test_reentrant_tab_factory_runs_once(app, tmp_path):
    host = tabs_host(tmp_path)
    host._tab_widgets['av1'] = None
    calls = []
    def create(key):
        calls.append(key)
        if len(calls) == 1:
            host._ensure_tab_loaded(1)
        return QWidget()
    host._create_tab_widget = create
    host._ensure_tab_loaded(1)
    assert calls == ['av1']
    assert tab_keys(host) == ['h265', 'av1', 'iso']
    host.deleteLater()


def test_tab_closed_during_factory_cannot_replace_a_different_tab(app, tmp_path):
    host = tabs_host(tmp_path)
    host._tab_widgets['av1'] = None
    def create(key):
        host._on_tab_close(1)
        return QWidget()
    host._create_tab_widget = create
    host._ensure_tab_loaded(1)
    assert tab_keys(host) == ['h265', 'iso']
    assert host._tab_widgets['av1'] is not None
    assert host._settings.value('tabs/visible/av1', type=bool) is False
    host.deleteLater()


def test_deleted_cached_tab_is_loaded_again(app, tmp_path):
    from PyQt6 import sip
    host = tabs_host(tmp_path)
    deleted = host._tab_widgets['av1']
    sip.delete(deleted)
    placeholder = QWidget()
    index = host.tabs.insertTab(1, placeholder, 'AV1')
    host.tabs.tabBar().setTabData(index, 'av1')
    created = []
    host._create_tab_widget = lambda key: created.append(QWidget()) or created[-1]
    host._ensure_tab_loaded(index)
    assert len(created) == 1
    assert host._tab_widgets['av1'] is created[0]
    host.deleteLater()


def test_iso_handoff_reopens_cached_hidden_converter(app, tmp_path):
    host = tabs_host(tmp_path)
    class ConvertWidget(QWidget):
        def __init__(self):
            super().__init__()
            self.received = []
        def add_dropped_files(self, paths): self.received.extend(paths)
    converter = ConvertWidget()
    old = host._tab_widgets['h265']
    host.tabs.removeTab(0)
    old.deleteLater()
    host._tab_widgets['h265'] = converter
    host._settings.setValue('tabs/visible/h265', False)
    host._handoff_iso_to_converter(['extracted.mkv'])
    assert converter.received == ['extracted.mkv']
    assert 'h265' in tab_keys(host)
    assert host.tabs.currentWidget() is converter
    assert host._settings.value('tabs/visible/h265', type=bool) is True
    host.deleteLater()


def test_main_window_close_waits_for_tab_construction(app, monkeypatch):
    from dragontools.gui import main_window_shutdown as module
    calls = []
    monkeypatch.setattr(module, '_close_with_budget', lambda *a: calls.append('close') or True)
    monkeypatch.setattr(module, 'begin_jellyfin_shutdown', lambda: None)
    monkeypatch.setattr(module, 'finish_jellyfin_shutdown', lambda *a: None)
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a: None)
    host = QMainWindow()
    host._tab_load_in_progress = {'av1'}
    assert module.prepare_main_window_close(host) is False
    assert calls == []
    host.deleteLater()


def menu_host():
    from dragontools.gui.main_window_menus import MainWindowMenuMixin
    class Host(MainWindowMenuMixin, QMainWindow):
        def __getattr__(self, name):
            if name.startswith('_'):
                return lambda *args, **kwargs: None
            raise AttributeError(name)
    host = Host()
    host.resets = []
    host._reset_defaults = lambda: host.resets.append('reset')
    host._init_menu()
    host._init_shortcuts()
    return host


@pytest.mark.parametrize('key', ['Ctrl+Q', 'Ctrl+R'])
def test_action_shortcut_is_registered_once(app, key):
    host = menu_host()
    sequence = QKeySequence(key)
    actions = [action for action in host.findChildren(QAction) if action.shortcut() == sequence]
    shortcuts = [shortcut for shortcut in host.findChildren(QShortcut) if shortcut.key() == sequence]
    assert len(actions) + len(shortcuts) == 1
    host.deleteLater()


def test_native_reset_shortcut_invokes_action_once(app):
    from PyQt6.QtTest import QTest
    host = menu_host()
    host.show()
    host.activateWindow()
    app.processEvents()
    QTest.keyClick(host, Qt.Key.Key_R, Qt.KeyboardModifier.ControlModifier)
    app.processEvents()
    assert host.resets == ['reset']
    host.deleteLater()


@pytest.mark.parametrize('data,offset', [
    (b'\x03\x00x', 0), (b'\x01\x00\x00\x00', 0),
    (b'\x04\x00x\x00', 0), (b'\x00\x00', -1),
])
def test_malformed_pidl_is_rejected_before_native_shell_use(data, offset):
    from dragontools.gui.drop_path_windows import extract_itemidlist_bytes
    assert extract_itemidlist_bytes(data, offset) == b''


def test_valid_pidl_keeps_its_complete_terminator():
    from dragontools.gui.drop_path_windows import extract_itemidlist_bytes
    assert extract_itemidlist_bytes(b'\x03\x00x\x00\x00', 0) == b'\x03\x00x\x00\x00'


@pytest.mark.skipif(os.name != 'nt', reason='Native Windows Shell CIDA round trip')
def test_native_shell_cida_resolves_owned_unicode_file(tmp_path):
    import ctypes
    from dragontools.gui.drop_path_windows import resolve_shell_idlist_to_paths
    from dragontools.core.path_syntax import path_compare_key
    source = tmp_path / 'Drag & Drop ä' / 'Film 你好.mkv'
    source.parent.mkdir()
    source.write_bytes(b'owned fixture')
    shell = ctypes.windll.shell32
    ole = ctypes.windll.ole32
    shell.SHParseDisplayName.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]
    shell.SHParseDisplayName.restype = ctypes.c_long
    shell.ILGetSize.argtypes = [ctypes.c_void_p]
    shell.ILGetSize.restype = ctypes.c_uint
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole.CoTaskMemFree.restype = None
    pointer = ctypes.c_void_p()
    attributes = ctypes.c_ulong()
    result = shell.SHParseDisplayName(str(source), None, ctypes.byref(pointer), 0, ctypes.byref(attributes))
    assert result >= 0 and pointer.value, hex(result & 0xffffffff)
    try:
        pidl = ctypes.string_at(pointer, shell.ILGetSize(pointer))
        payload = struct.pack('<III', 1, 12, 14) + b'\x00\x00' + pidl
        resolved = resolve_shell_idlist_to_paths(payload)
        assert [path_compare_key(path) for path in resolved] == [path_compare_key(str(source))]
    finally:
        ole.CoTaskMemFree(pointer)


@pytest.mark.skipif(os.name != 'nt', reason='Windows Shell CIDA contract')
def test_cida_header_offset_never_reaches_shell_combine(monkeypatch):
    import ctypes
    from dragontools.gui.drop_path_windows import resolve_shell_idlist_to_paths
    calls = []
    class Function:
        def __call__(self, *args):
            calls.append(args)
            return None
    shell = SimpleNamespace(ILCombine=Function(), ILFree=Function(), SHGetPathFromIDListW=Function())
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(shell32=shell))
    payload = struct.pack('<III', 1, 0, 12) + b'\x03\x00x\x00\x00'
    assert resolve_shell_idlist_to_paths(payload) == []
    assert calls == []


@pytest.mark.parametrize('extension', ['.mkv', '.mp4'])
def test_video_list_rejects_nonexistent_video_candidate(app, tmp_path, extension):
    from PyQt6.QtWidgets import QListWidget
    from dragontools.gui.video_file_input import add_video_paths_to_list
    files = QListWidget()
    assert add_video_paths_to_list(files, [str(tmp_path / ('missing' + extension))]) == 0
    assert files.count() == 0
    files.deleteLater()


def log_host():
    from dragontools.gui.main_window_convert_actions import MainWindowConvertActionsMixin
    class Host(MainWindowConvertActionsMixin, QMainWindow):
        pass
    host = Host()
    host.tabs = QTabWidget(host)
    host.setCentralWidget(host.tabs)
    logs = []
    for codec in ['h265', 'av1']:
        widget = QWidget()
        widget.log_edit = QTextEdit(widget)
        widget.log_edit.setPlainText(codec + ' log')
        logs.append(widget.log_edit)
        index = host.tabs.addTab(widget, codec)
        host.tabs.tabBar().setTabData(index, codec)
    host.tabs.setCurrentIndex(1)
    host._open_log_zoom_window()
    dialog = next(dialog for dialog in host.findChildren(QDialog) if dialog.windowTitle() == '📋 Logging-Fenster')
    return host, logs, dialog, dialog.findChild(QTextEdit)


def test_log_window_mirrors_active_tab(app):
    host, logs, dialog, view = log_host()
    assert view.toPlainText() == logs[1].toPlainText()
    dialog.reject()
    host.deleteLater()


def test_log_window_tracks_reset_and_same_length_replacement(app):
    host, logs, dialog, view = log_host()
    # Test the source selected by the current implementation independently of
    # which tab it chose, so reset/replacement is a separate regression.
    source = next(log for log in logs if log.toPlainText() == view.toPlainText())
    source.setPlainText('short')
    assert view.toPlainText() == 'short'
    source.setPlainText('other')
    assert view.toPlainText() == 'other'
    source.clear()
    assert view.toPlainText() == ''
    dialog.reject()
    host.deleteLater()


def test_log_window_survives_deleted_source_without_qt_callback_exception(tmp_path):
    # Record exceptions from native Qt signals instead of letting PyQt abort
    # the whole test host; all exercised objects are created in this child.
    script = '''
import sys
from PyQt6 import sip
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QSettings
from dragontools.tests.test_patch21_gui_contracts import log_host
from dragontools.gui import ui_helpers
ui_helpers.QSettings=lambda *args: QSettings(sys.argv[1],QSettings.Format.IniFormat)
app=QApplication([])
errors=[]
sys.excepthook=lambda *exc: errors.append(str(exc[1]))
host,logs,dialog,view=log_host()
source=next(log for log in logs if log.toPlainText()==view.toPlainText())
sip.delete(source)
dialog.reject()
app.processEvents()
if errors:
    print(repr(errors))
    raise SystemExit(1)
host.deleteLater()
app.processEvents()
'''
    result = subprocess.run([sys.executable, '-B', '-c', script, str(tmp_path / 'geometry.ini')], env=dict(os.environ, QT_QPA_PLATFORM='offscreen'),
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr + result.stdout


@pytest.fixture(autouse=True)
def isolated_geometry_settings(tmp_path, monkeypatch):
    from dragontools.gui import ui_helpers
    monkeypatch.setattr(ui_helpers, 'QSettings', lambda *args: QSettings(str(tmp_path / 'geometry.ini'), QSettings.Format.IniFormat))


def test_native_metadata_worker_remains_reserved_until_queued_finish(app, monkeypatch):
    from PyQt6.QtCore import QThread
    from dragontools.gui import main_window_metadata_actions as module
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, 'information', lambda *args: None)
    class Worker(QThread):
        def run(self): pass
    host = QMainWindow()
    first, second = Worker(host), Worker(host)
    assert module._start_metadata_action_thread(host, first, status_text='first')
    assert first.wait(3000)
    assert not module._start_metadata_action_thread(host, second, status_text='second')
    assert host._metadata_action_thread is first
    app.processEvents()
    assert host._metadata_action_thread is None
    host.deleteLater()


def test_stop_metadata_suppresses_already_queued_native_result(app, monkeypatch):
    from PyQt6.QtCore import QThread, pyqtSignal
    from dragontools.gui import main_window_metadata_actions as module
    from dragontools.core import online_metadata
    from PyQt6.QtWidgets import QMessageBox
    messages = []
    monkeypatch.setattr(QMessageBox, 'information', lambda *args: messages.append(args))
    monkeypatch.setattr(online_metadata, 'config_from_settings', lambda *args, **kwargs: object())
    class Worker(QThread):
        completed = pyqtSignal(object, object)
        def __init__(self, config, parent): super().__init__(parent)
        def run(self): self.completed.emit(['OK'], [])
    monkeypatch.setattr(module, 'OnlineMetadataConnectionTestThread', Worker)
    host = QMainWindow()
    host._settings = object()
    module.MainWindowMetadataActionsMixin._test_tmdb_connection(host)
    worker = host._metadata_action_thread
    assert worker.wait(3000)
    assert module.stop_metadata_action_thread(host)
    app.processEvents()
    assert messages == []
    host.deleteLater()


def test_closed_log_window_has_no_source_signal_connection(app):
    host, logs, dialog, view = log_host()
    source = next(log for log in logs if log.toPlainText() == view.toPlainText())
    dialog.reject()
    assert source.receivers(source.textChanged) == 0
    host.deleteLater()


def test_metadata_action_reservation_lasts_until_finished_callback(app, monkeypatch):
    from dragontools.gui import main_window_metadata_actions as module
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, 'information', lambda *args: None)
    class Signal:
        def __init__(self): self.callbacks = []
        def connect(self, callback): self.callbacks.append(callback)
        def emit(self):
            for callback in self.callbacks: callback()
    class Worker:
        def __init__(self): self.finished, self.starts, self.deleted = Signal(), 0, False
        def isRunning(self): return False
        def start(self): self.starts += 1
        def deleteLater(self): self.deleted = True
    host = QMainWindow()
    first, second = Worker(), Worker()
    assert module._start_metadata_action_thread(host, first, status_text='first')
    assert not module._start_metadata_action_thread(host, second, status_text='second')
    assert first.starts == 1 and second.starts == 0
    assert host._metadata_action_thread is first
    first.finished.emit()
    assert host._metadata_action_thread is None
    host.deleteLater()


def test_stale_metadata_cleanup_cannot_clear_new_job_status(app):
    from dragontools.gui import main_window_metadata_actions as module
    class Signal:
        def connect(self, callback): self.callback = callback
    first = SimpleNamespace(isRunning=lambda: False, finished=Signal(), start=lambda: None, deleteLater=lambda: None)
    host = QMainWindow()
    assert module._start_metadata_action_thread(host, first, status_text='first')
    second = object()
    host._metadata_action_thread = second
    host.statusBar().showMessage('second')
    first.finished.callback()
    assert host._metadata_action_thread is second
    assert host.statusBar().currentMessage() == 'second'
    host.deleteLater()


def test_help_dialog_is_released_after_each_modal_invocation(app, monkeypatch):
    from dragontools.gui import help_dialog
    from dragontools.gui.main_window_help_actions import MainWindowHelpActionsMixin
    class DummyHelp(QDialog):
        def __init__(self, parent):
            super().__init__(parent)
            from dragontools.gui.ui_helpers import install_persistent_window_geometry
            install_persistent_window_geometry(self, "p21_modal_fixture")
            QTimer.singleShot(0, self.accept)
    monkeypatch.setattr(help_dialog, 'HelpDialog', DummyHelp)
    host = QMainWindow()
    for _ in range(3):
        MainWindowHelpActionsMixin._open_help(host)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert host.findChildren(DummyHelp) == []
    host.deleteLater()


def test_bullet_first_changelog_block_does_not_duplicate_first_entry():
    from dragontools.gui.changelog_dialog import _block_to_html
    html = _block_to_html('- First item\n- Second item')
    assert html.count('First item') == 1
    assert html.count('Second item') == 1


def test_dark_mode_reaches_main_window_controls(app):
    from PyQt6.QtGui import QPalette
    from PyQt6.QtWidgets import QPushButton
    from dragontools.gui.main_window_profile_actions import MainWindowProfileActionsMixin
    from dragontools.gui.styles import STYLE_LIGHT
    original_style = app.styleSheet()
    host = QMainWindow()
    button = QPushButton('Button', host)
    host.setStyleSheet(STYLE_LIGHT)
    host.setCentralWidget(button)
    host.show()
    app.processEvents()
    light = button.palette().color(QPalette.ColorRole.Button).name()
    try:
        MainWindowProfileActionsMixin._toggle_dark(host, True)
        app.processEvents()
        dark = button.palette().color(QPalette.ColorRole.Button).name()
        assert dark != light
    finally:
        app.setStyleSheet(original_style)
        host.deleteLater()


@pytest.mark.skipif(os.name != 'nt', reason='Native Windows ANSI clipboard encoding')
def test_windows_ansi_filename_payload_keeps_unicode_name():
    from dragontools.gui.drop_path_decode import decode_windows_filename_payload
    path = r'C:\Märku\Film ä.mkv'
    assert decode_windows_filename_payload(path.encode('mbcs') + b'\x00', utf16=False) == [path]


@pytest.mark.parametrize('suffix', [b'\x00', b'\x00\xd8'])
def test_invalid_utf16_payload_cannot_silently_select_a_different_name(suffix):
    from dragontools.gui.drop_path_decode import decode_windows_filename_payload
    raw = r'C:\Media\Film.mkv'.encode('utf-16-le') + suffix
    assert decode_windows_filename_payload(raw, utf16=True) == []


def test_plain_text_drop_uses_the_same_path_deduplication_as_urls(tmp_path):
    from PyQt6.QtCore import QMimeData
    from dragontools.gui.drop_path_extractor import _extract_paths_from_mime_data
    path = tmp_path / 'Film ä.mkv'
    path.write_bytes(b'video')
    mime = QMimeData()
    mime.setText(str(path) + '\n' + str(path))
    assert _extract_paths_from_mime_data(mime) == [str(path)]


@pytest.mark.parametrize('url,expected', [
    ('file:///Media/My%2520Movie.mkv', '/Media/My%20Movie.mkv'),
    ('file://server/share/video.mkv', '//server/share/video.mkv'),
])
def test_posix_file_url_is_decoded_once_and_keeps_network_root(monkeypatch, url, expected):
    from dragontools.gui import drop_path_decode as module
    monkeypatch.setattr(module, 'os', SimpleNamespace(name='posix'))
    assert module.reconstruct_local_path_from_url_string(url) == expected


def test_native_help_fragment_navigation_keeps_loaded_html(app, tmp_path, monkeypatch):
    from PyQt6.QtCore import QPoint
    from PyQt6.QtGui import QTextCursor
    from PyQt6.QtTest import QTest
    from dragontools.gui import help_dialog as module
    path = tmp_path / 'help.html'
    path.write_text('<a href="#target">Jump</a><p>Help fixture</p>' + '<p>Space</p>' * 80 + '<h2 id="target">Target</h2>', encoding='utf-8')
    monkeypatch.setattr(module, 'FROZEN', True)
    monkeypatch.setattr(module, '_find_help', lambda: str(path))
    dialog = module.HelpDialog()
    dialog.show()
    app.processEvents()
    browser = dialog._browser
    cursor = browser.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.Start)
    rectangle = browser.cursorRect(cursor)
    point = QPoint(rectangle.left() + 3, rectangle.center().y())
    assert browser.anchorAt(point) == '#target'
    QTest.mouseClick(browser.viewport(), Qt.MouseButton.LeftButton, pos=point)
    app.processEvents()
    assert 'Help fixture' in browser.toPlainText()
    assert browser.verticalScrollBar().value() > 0
    dialog.reject()
    dialog.deleteLater()


@pytest.mark.parametrize('module_name,class_name,action', [
    ('settings_dialog', 'SettingsDialog', '_open_settings'),
    ('save_settings_dialog', 'SaveSettingsDialog', '_open_settings_save'),
    ('timeout_settings_dialog', 'TimeoutSettingsDialog', '_open_timeout_settings'),
    ('rules_dialog', 'RulesDialog', '_open_rules'),
    ('online_metadata_dialog', 'OnlineMetadataDialog', '_open_online_metadata_settings'),
    ('media_library_dialog', 'MediaLibraryDialog', '_open_media_library'),
])
def test_main_settings_modals_release_completed_dialogs(app, monkeypatch, module_name, class_name, action):
    import importlib
    from dragontools.gui.main_window_settings_actions import MainWindowSettingsActionsMixin
    class DummyDialog(QDialog):
        def __init__(self, parent, **kwargs):
            super().__init__(parent)
            from dragontools.gui.ui_helpers import install_persistent_window_geometry
            install_persistent_window_geometry(self, "p21_modal_fixture")
            QTimer.singleShot(0, self.accept)
    module = importlib.import_module('dragontools.gui.' + module_name)
    monkeypatch.setattr(module, class_name, DummyDialog)
    class Host(MainWindowSettingsActionsMixin, QMainWindow):
        def _reload_all_paths(self): self.reloads += 1
    host = Host()
    host.reloads = 0
    for _ in range(3):
        getattr(host, action)()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert host.findChildren(DummyDialog) == []
    assert host.reloads == (3 if action in ('_open_settings', '_open_settings_save') else 0)
    host.deleteLater()


def test_completed_tab_manager_is_released_and_visibility_applied(app, tmp_path, monkeypatch):
    from dragontools.gui import main_window_tabs as module
    class DummyDialog(QDialog):
        def __init__(self, parent):
            super().__init__(parent)
            from dragontools.gui.ui_helpers import install_persistent_window_geometry
            install_persistent_window_geometry(self, "p21_modal_fixture")
            QTimer.singleShot(0, self.accept)
    monkeypatch.setattr(module, 'TabManagerDialog', DummyDialog)
    host = tabs_host(tmp_path)
    applied = []
    host._apply_tab_visibility = lambda: applied.append(True)
    for _ in range(3):
        host._open_tab_manager()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert len(applied) == 3
    assert host.findChildren(DummyDialog) == []
    host.deleteLater()


def test_completed_profile_manager_dialog_is_released(app, monkeypatch):
    from dragontools.gui import profile_manager_dialog as module
    class DummyDialog(QDialog):
        def __init__(self, widget, parent):
            super().__init__(parent)
            from dragontools.gui.ui_helpers import install_persistent_window_geometry
            install_persistent_window_geometry(self, "p21_modal_fixture")
            QTimer.singleShot(0, self.accept)
    monkeypatch.setattr(module, 'ProfileManagerDialog', DummyDialog)
    host = QMainWindow()
    tabs = QTabWidget(host)
    converter = QWidget()
    converter.profile_manager = object()
    tabs.addTab(converter, 'Converter')
    for _ in range(3):
        module.open_profile_manager(tabs, parent=host)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert host.findChildren(DummyDialog) == []
    host.deleteLater()


def test_stale_update_completion_preserves_current_checker_and_status(app, monkeypatch):
    from dragontools.core.update_check import UpdateCheckResult
    from dragontools.gui import main_window_help_actions as module
    messages = []
    monkeypatch.setattr(module.QMessageBox, 'information', lambda *args: messages.append(args))
    host = QMainWindow()
    old, current = QWidget(), QWidget()
    host._github_update_checker = current
    host.statusBar().showMessage('Current check')
    module.MainWindowHelpActionsMixin._handle_update_result(host, UpdateCheckResult(False, error='old'), True, old)
    assert host._github_update_checker is current
    assert host.statusBar().currentMessage() == 'Current check'
    assert messages == []
    current.deleteLater()
    host.deleteLater()


@pytest.mark.parametrize('caller', ['main', 'tabs'])
def test_external_launcher_skips_legacy_directory_and_uses_executable(app, tmp_path, monkeypatch, caller):
    from dragontools.gui import tab_manager, main_window_system_actions
    from dragontools.core import tool_paths
    directory = tmp_path / 'HandBrake.exe'
    directory.mkdir()
    executable = tmp_path / 'Programme ä' / 'HandBrake.exe'
    executable.parent.mkdir()
    executable.write_bytes(b'fixture')
    launched, prompted = [], []
    tools = SimpleNamespace(find_in_settings=lambda *args: None)
    monkeypatch.setattr(main_window_system_actions, 'get_tool_paths', lambda: tools)
    monkeypatch.setattr(tool_paths, 'get_tool_paths', lambda: tools)
    monkeypatch.setattr(tool_paths, 'find_tool_in_settings', lambda *args: None)
    monkeypatch.setattr(tab_manager, '_find_bundled_exe', lambda name: str(executable))
    monkeypatch.setattr(tab_manager, '_open_external', lambda path: launched.append(path))
    monkeypatch.setattr(tab_manager.QFileDialog, 'getOpenFileName', lambda *args: prompted.append(True) or ('', ''))
    host = QMainWindow()
    host._settings = QSettings(str(tmp_path / 'external.ini'), QSettings.Format.IniFormat)
    host._settings.setValue('tools/external/HandBrake.exe', str(directory))
    if caller == 'main':
        main_window_system_actions.MainWindowSystemActionsMixin._launch_external(host, 'HandBrake.exe')
    else:
        tab_manager.TabManagerDialog._launch(host, 'HandBrake.exe')
    assert launched == [str(executable)]
    assert prompted == []
    host.deleteLater()


def test_bundle_lookup_rejects_directory_named_exe(tmp_path, monkeypatch):
    from dragontools.gui import tab_manager
    monkeypatch.setattr(tab_manager, 'EXE_DIR', tmp_path)
    (tmp_path / 'HandBrake.exe').mkdir()
    assert tab_manager._find_bundled_exe('HandBrake.exe') is None


@pytest.mark.parametrize('caller', ['main', 'tabs'])
@pytest.mark.parametrize('configured', [False, True])
def test_resolve_launch_uses_central_key_then_standard_installation(app, tmp_path, monkeypatch, caller, configured):
    from dragontools.gui import tab_manager, main_window_system_actions
    from dragontools.core import tool_paths
    selected, installed = tmp_path / 'Chosen Resolve.exe', tmp_path / 'Installed Resolve.exe'
    selected.write_bytes(b'fixture')
    installed.write_bytes(b'fixture')
    lookups, launches = [], []
    def lookup(*args):
        lookups.append(args)
        return str(selected) if configured else None
    tools = SimpleNamespace(find_in_settings=lookup, davinci_resolve=str(installed))
    monkeypatch.setattr(main_window_system_actions, 'get_tool_paths', lambda: tools)
    monkeypatch.setattr(tool_paths, 'get_tool_paths', lambda: tools)
    monkeypatch.setattr(tool_paths, 'find_tool_in_settings', lookup)
    monkeypatch.setattr(tab_manager, '_open_external', lambda path: launches.append(path))
    monkeypatch.setattr(tab_manager, '_find_bundled_exe', lambda name: pytest.fail('Resolve should be found centrally'))
    monkeypatch.setattr(tab_manager.QFileDialog, 'getOpenFileName', lambda *args: pytest.fail('Unexpected file chooser'))
    host = QMainWindow()
    host._settings = QSettings(str(tmp_path / 'resolve.ini'), QSettings.Format.IniFormat)
    if caller == 'main':
        main_window_system_actions.MainWindowSystemActionsMixin._launch_external(host, 'Resolve.exe')
    else:
        tab_manager.TabManagerDialog._launch(host, 'Resolve.exe')
    assert lookups == [('davinci_resolve', 'Resolve.exe', 'resolve')]
    assert launches == [str(selected if configured else installed)]
    host.deleteLater()
