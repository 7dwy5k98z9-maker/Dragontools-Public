from types import SimpleNamespace
from unittest.mock import Mock
import subprocess
import sys

import pytest
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import QApplication, QMessageBox, QWidget

from dragontools.gui import main_window_shutdown as shutdown
from dragontools.gui import force_application_exit as emergency


@pytest.mark.parametrize('choice', ['force', 'cancel', 'escape'])
def test_emergency_dialog_buttons(qtbot, choice):
    window = QWidget()
    qtbot.addWidget(window)
    def respond():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QMessageBox)
        buttons = {button.text(): button for button in dialog.buttons()}
        assert set(buttons) == {'Trotzdem beenden', 'Abbrechen'}
        assert dialog.defaultButton() is buttons['Abbrechen']
        if choice == 'escape':
            qtbot.keyClick(dialog, Qt.Key.Key_Escape)
        else:
            qtbot.mouseClick(buttons['Trotzdem beenden' if choice == 'force' else 'Abbrechen'],
                             Qt.MouseButton.LeftButton)
    QTimer.singleShot(0, respond)
    assert shutdown._confirm_force_quit(window, 'Beenden', 'Worker läuft noch') is (choice == 'force')


@pytest.mark.parametrize('stage', ['worker', 'unknown', 'metadata', 'watch', 'jellyfin', 'late'])
@pytest.mark.parametrize('force', [False, True])
def test_every_blocked_shutdown_offers_force_exit(monkeypatch, stage, force):
    window = SimpleNamespace(_tab_widgets={})
    calls = []
    monkeypatch.setattr(shutdown, 'begin_jellyfin_shutdown', lambda: None)
    monkeypatch.setattr(shutdown, 'finish_jellyfin_shutdown', lambda ok: None)
    monkeypatch.setattr(shutdown, 'application_worker_sources', lambda _: [])
    def workers(*args, **kwargs):
        calls.append('workers')
        if stage == 'unknown':
            raise RuntimeError('undefined state')
        blocked = stage == 'worker' or (stage == 'late' and calls.count('workers') == 2)
        return SimpleNamespace(ok=not blocked, still_running=('stuck',))
    monkeypatch.setattr(shutdown, 'shutdown_loaded_widgets', workers)
    monkeypatch.setattr(shutdown, 'stop_metadata_action_thread', lambda *a, **kw: stage != 'metadata')
    monkeypatch.setattr(shutdown, 'stop_watch_folder_controller',
                        lambda *a, **kw: kw['timeout_ms'] == 0 or stage != 'watch')
    monkeypatch.setattr(shutdown, 'stop_jellyfin_workers', lambda **kw: stage != 'jellyfin')
    confirm, exit_now = Mock(return_value=force), Mock()
    monkeypatch.setattr(shutdown, '_confirm_force_quit', confirm)
    monkeypatch.setattr(shutdown, 'force_application_exit', exit_now)
    assert shutdown.prepare_main_window_close(window, timeout_ms=8000) is False
    confirm.assert_called_once()
    assert exit_now.call_count == int(force)


@pytest.mark.parametrize('taskkill_fails', [False, True])
def test_force_exit_is_bounded_and_always_uses_hard_exit(monkeypatch, taskkill_fails):
    class Exited(BaseException):
        pass
    def hard_exit(code):
        assert code == 1
        raise Exited
    def kill(*args, **kwargs):
        if taskkill_fails:
            raise OSError('cannot create process')
    run = Mock(side_effect=kill)
    monkeypatch.setattr(emergency.sys, 'platform', 'win32')
    monkeypatch.setattr(emergency.os, 'getpid', lambda: 12345)
    monkeypatch.setattr(emergency.os, '_exit', hard_exit)
    monkeypatch.setattr(emergency.subprocess, 'run', run)
    with pytest.raises(Exited):
        emergency.force_application_exit()
    assert run.call_args.args[0][1:] == ['/PID', '12345', '/T', '/F']
    assert run.call_args.kwargs['timeout'] == 3
    assert run.call_args.kwargs['creationflags'] == subprocess.CREATE_NO_WINDOW


def test_emergency_exit_escapes_a_stuck_python_thread(tmp_path):
    # Isolate the real hard-exit in its own process. It must never kill pytest.
    script = '''
import threading
from dragontools.gui.force_application_exit import force_application_exit
threading.Thread(target=threading.Event().wait).start()
print('EMERGENCY_READY', flush=True)
force_application_exit()
raise RuntimeError('emergency exit returned')
'''
    from pathlib import Path
    package_root = str(Path(__file__).resolve().parents[2])
    result = subprocess.run([sys.executable, '-B', '-c', script], cwd=package_root,
                            capture_output=True, timeout=10)
    assert b'EMERGENCY_READY' in result.stdout
    assert result.returncode != 0
    assert b'emergency exit returned' not in result.stderr
