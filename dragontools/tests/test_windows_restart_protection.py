"""Native shutdown vetoes, visible registration state and persistent diagnostics."""
from ctypes import wintypes
import ctypes
import json
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from PyQt6.QtCore import QByteArray
from PyQt6.QtWidgets import QMainWindow

from dragontools.core.restart_guard_diagnostics import RestartGuardDiagnostics
from dragontools.core.windows_restart_api import WindowsRestartAPI
from dragontools.core.windows_restart_policy import clear_user_initiated_shutdown
from dragontools.gui.windows_restart_guard import WindowsRestartGuard
from dragontools.gui.windows_restart_native import WM_QUERYENDSESSION, WM_ENDSESSION, ENDSESSION_CRITICAL


@pytest.fixture
def guard(qtbot, tmp_path, monkeypatch):
    if os.name != "nt":
        pytest.skip("Windows-specific GUI restart protection")
    clear_user_initiated_shutdown()
    window = QMainWindow()
    qtbot.addWidget(window)
    window._tab_widgets = {}
    # Avoid real Windows registrations in unit tests; native API integration
    # below uses a separate, real window and never initiates system shutdown.
    api = SimpleNamespace(query=Mock(return_value=""), create=Mock(side_effect=lambda _h, reason: reason),
                          destroy=Mock(), prioritize=Mock(), restore_priority=Mock())
    # Suppress only the constructor's queued first refresh; each test controls
    # exactly when registration runs. The production timer is stopped below.
    with monkeypatch.context() as startup:
        startup.setattr("dragontools.gui.windows_restart_guard.QTimer.singleShot", lambda *_: None)
        instance = WindowsRestartGuard(window, api=api, diagnostics=RestartGuardDiagnostics(tmp_path/'logs'))
    instance._timer.stop()
    monkeypatch.setattr(instance, "_active_worker_names", lambda: ("ConverterThread",))
    monkeypatch.setattr(instance, "_show_block_notice", Mock())
    yield instance, window, api
    instance.dispose()
    clear_user_initiated_shutdown()


def _events(guard):
    path = guard._diagnostics.path
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


@pytest.mark.parametrize("flags", [0, 1, ENDSESSION_CRITICAL, 0x80000000, ENDSESSION_CRITICAL | 1])
def test_native_query_returns_win32_false_without_aborting_workers(guard, flags):
    instance, window, api = guard
    abort = Mock()
    worker = SimpleNamespace(isRunning=lambda: True, request_abort=abort)
    window._tab_widgets = {"convert": SimpleNamespace(iter_shutdown_workers=lambda: (worker,))}
    assert instance.handle_native_message(WM_QUERYENDSESSION, 0, flags) == (True, 0)
    abort.assert_not_called()
    assert _events(instance)[-1]["event"] == "native_query_rejected"
    assert _events(instance)[-1]["critical"] is bool(flags & ENDSESSION_CRITICAL)


def test_native_filter_handles_windows_msg_and_preserves_veto_result(guard):
    instance, _, _ = guard
    message = wintypes.MSG()
    message.message, message.wParam, message.lParam = WM_QUERYENDSESSION, 0, ENDSESSION_CRITICAL
    assert instance._native_filter.nativeEventFilter(
        QByteArray(b"windows_generic_MSG"), ctypes.addressof(message),
    ) == (True, 0)


def test_non_session_native_messages_are_not_intercepted(guard):
    instance, _, _ = guard
    assert instance.handle_native_message(0x0100, 0, 0) == (False, 0)
    message = wintypes.MSG()
    message.message = WM_QUERYENDSESSION
    assert instance._native_filter.nativeEventFilter(
        QByteArray(b"xcb_generic_event_t"), ctypes.addressof(message),
    ) == (False, 0)


def test_native_query_in_idle_app_is_left_to_existing_qt_user_decision(guard, monkeypatch):
    instance, _, _ = guard
    monkeypatch.setattr(instance, "_active_worker_names", lambda: ())
    assert instance.handle_native_message(WM_QUERYENDSESSION, 0, 0) == (False, 0)


def test_explicit_dragontools_shutdown_remains_allowed(guard, monkeypatch):
    from dragontools.gui import windows_restart_guard as module
    instance, _, api = guard
    instance.refresh()
    monkeypatch.setattr(module, "user_initiated_shutdown_allowed", lambda: True)
    assert instance.handle_native_message(WM_QUERYENDSESSION, 0, 0) == (False, 0)
    assert not instance._block_reason
    api.restore_priority.assert_called()


def test_registration_is_verified_and_disappearing_registration_is_repaired(guard):
    instance, _, api = guard
    instance.refresh()
    reason = instance._block_reason
    assert reason and instance._last_status[0] == "aktiv"
    api.query.return_value = reason
    instance.refresh()
    assert api.create.call_count == 1
    api.query.side_effect = OSError("registration vanished")
    instance.refresh()
    assert api.create.call_count == 2
    assert instance._last_status[0] == "aktiv"


def test_failed_registration_is_visible_logged_and_retried(guard):
    instance, window, api = guard
    api.create.side_effect = OSError(5, "access denied")
    instance.refresh()
    assert not instance._block_reason
    assert instance._last_status[0] == "eingeschränkt"
    assert "eingeschränkt" in instance._status_label.text()
    assert any(row["event"] == "registration_failed" and "access denied" in row["error"]
               for row in _events(instance))
    # Native veto remains usable independently of a failed reason registration.
    assert instance.handle_native_message(WM_QUERYENDSESSION, 0, 0) == (True, 0)
    api.create.side_effect = lambda _hwnd, reason: reason
    instance.refresh()
    assert instance._last_status[0] == "aktiv"


def test_finishing_work_releases_registration_and_restores_priority(guard, monkeypatch):
    instance, _, api = guard
    instance.refresh()
    hwnd = instance._blocked_hwnd
    monkeypatch.setattr(instance, "_active_worker_names", lambda: ())
    instance.refresh()
    api.destroy.assert_called_once_with(hwnd)
    api.restore_priority.assert_called()
    assert not instance._block_reason and instance._last_status[0] == "bereit"


def test_unresolved_worker_discovery_keeps_native_query_blocked(guard, monkeypatch):
    instance, _, _ = guard
    monkeypatch.setattr(instance, "_active_worker_names", Mock(side_effect=RuntimeError("broken provider")))
    assert instance.handle_native_message(WM_QUERYENDSESSION, 0, 0) == (True, 0)
    assert any(row["event"] == "worker_discovery_failed" for row in _events(instance))


def test_start_reservation_is_protected_before_worker_isrunning(guard, monkeypatch):
    instance, window, _ = guard
    monkeypatch.setattr(instance, "_active_worker_names", WindowsRestartGuard._active_worker_names.__get__(instance))
    window._tab_widgets = {"convert": SimpleNamespace(_state=SimpleNamespace(start_reserved=True))}
    assert "gestartet" in instance._active_worker_names()[0]
    assert instance.handle_native_message(WM_QUERYENDSESSION, 0, 0) == (True, 0)


def test_snoozed_restart_remains_vetoed_while_idle(guard, monkeypatch):
    from dragontools.gui.windows_restart_guard import time
    instance, _, _ = guard
    monkeypatch.setattr(instance, "_active_worker_names", lambda: ())
    instance._snoozed_until = time.monotonic() + 60
    assert instance.handle_native_message(WM_QUERYENDSESSION, 0, 0) == (True, 0)


def test_forced_session_end_is_recorded_without_claiming_it_was_prevented(guard):
    instance, _, _ = guard
    assert instance.handle_native_message(WM_ENDSESSION, 1, ENDSESSION_CRITICAL) == (False, 0)
    event = _events(instance)[-1]
    assert event["event"] == "native_session_end" and event["ending"] and event["critical"]
    assert event["workers"] == ["ConverterThread"]


def test_cancelled_session_end_is_distinguished_in_diagnostics(guard):
    instance, _, _ = guard
    instance.handle_native_message(WM_ENDSESSION, 0, 0)
    assert _events(instance)[-1]["ending"] is False


def test_qt_cancel_failure_is_visible_without_false_block_notice(guard):
    instance, _, _ = guard
    manager = SimpleNamespace(allowsInteraction=lambda: False, cancel=Mock(side_effect=RuntimeError("Qt error")))
    instance.handle_commit_data_request(manager)
    assert instance._last_status[0] == "eingeschränkt"
    instance._show_block_notice.assert_not_called()
    assert any(event["event"] == "qt_cancel_failed" for event in _events(instance))


def test_disposed_guard_does_not_intercept_further_messages(guard):
    instance, _, _ = guard
    instance.dispose()
    assert instance._native_filter is None
    assert instance.handle_native_message(WM_QUERYENDSESSION, 0, 0) == (False, 0)


def test_native_callback_error_still_rejects_shutdown_query(guard, monkeypatch):
    instance, _, _ = guard
    monkeypatch.setattr(instance, "handle_native_message", Mock(side_effect=RuntimeError("callback failure")))
    message = wintypes.MSG()
    message.message = WM_QUERYENDSESSION
    assert instance._native_filter.nativeEventFilter(
        QByteArray(b"windows_generic_MSG"), ctypes.addressof(message),
    ) == (True, 0)
    assert instance._last_status[0] == "eingeschränkt"
    assert any(row["event"] == "native_filter_failed" for row in _events(instance))


def test_recreated_native_window_is_protected_even_when_old_handle_is_gone(guard, monkeypatch):
    instance, _, api = guard
    instance.refresh()
    api.destroy.side_effect = OSError(1400, "old HWND destroyed")
    monkeypatch.setattr(instance, "_hwnd", lambda: 0x12345678)
    instance.refresh()
    assert instance._blocked_hwnd == 0x12345678 and instance._last_status[0] == "aktiv"
    assert any(row["event"] == "old_window_release_failed" for row in _events(instance))


def test_priority_failure_is_reported_while_native_veto_remains_available(guard):
    instance, _, api = guard
    api.prioritize.side_effect = OSError("priority denied")
    assert instance.handle_native_message(WM_QUERYENDSESSION, 0, 0) == (True, 0)
    assert instance._last_status[0] == "eingeschränkt"
    assert not instance._block_reason
    assert any(row["event"] == "registration_failed" for row in _events(instance))


def test_registration_query_failure_after_create_retains_cleanup_ownership(guard):
    instance, _, api = guard
    api.create.side_effect = OSError("verification query failed after create")
    instance.refresh()
    hwnd = instance._blocked_hwnd
    assert hwnd
    instance.release()
    api.destroy.assert_called_once_with(hwnd)


def test_log_failure_is_visible_and_does_not_disable_native_veto(guard):
    instance, _, _ = guard
    instance._diagnostics.path = instance._diagnostics.path.parent  # becomes a directory
    instance._diagnostics.path.mkdir(parents=True, exist_ok=True)
    assert instance.handle_native_message(WM_QUERYENDSESSION, 0, 0) == (True, 0)
    assert "Protokollfehler" in instance._status_label.text()


def _fake_libraries():
    reason = [""]
    user32, kernel32 = Mock(), Mock()
    def create(hwnd, text):
        reason[0] = text
        return 1
    def query(hwnd, buffer, size):
        buffer.value = reason[0]
        return 1
    def get_priority(level, flags):
        ctypes.cast(level, ctypes.POINTER(wintypes.DWORD))[0] = 0x280
        ctypes.cast(flags, ctypes.POINTER(wintypes.DWORD))[0] = 0
        return 1
    user32.ShutdownBlockReasonCreate.side_effect = create
    user32.ShutdownBlockReasonQuery.side_effect = query
    user32.ShutdownBlockReasonDestroy.return_value = 1
    kernel32.GetProcessShutdownParameters.side_effect = get_priority
    kernel32.SetProcessShutdownParameters.return_value = 1
    return user32, kernel32


def test_api_keeps_pointer_sized_hwnd_and_verifies_reason():
    user32, kernel32 = _fake_libraries()
    api = WindowsRestartAPI(user32=user32, kernel32=kernel32)
    hwnd = (1 << 40) + 123
    assert api.create(hwnd, "DragonTools verarbeitet Dateien") == "DragonTools verarbeitet Dateien"
    user32.ShutdownBlockReasonCreate.assert_called_once_with(hwnd, "DragonTools verarbeitet Dateien")
    assert user32.ShutdownBlockReasonCreate.argtypes[0] is wintypes.HWND
    assert ctypes.sizeof(wintypes.HWND) == ctypes.sizeof(ctypes.c_void_p)


def test_api_false_return_is_a_real_error_not_a_claimed_registration():
    user32, kernel32 = _fake_libraries()
    user32.ShutdownBlockReasonCreate.side_effect = None
    user32.ShutdownBlockReasonCreate.return_value = 0
    with pytest.raises(OSError, match="registrieren"):
        WindowsRestartAPI(user32=user32, kernel32=kernel32).create(123, "busy")


def test_priority_uses_application_range_and_restores_original_settings():
    user32, kernel32 = _fake_libraries()
    api = WindowsRestartAPI(user32=user32, kernel32=kernel32)
    api.prioritize()
    api.prioritize()
    kernel32.SetProcessShutdownParameters.assert_called_once_with(0x3FF, 0)
    api.restore_priority()
    assert kernel32.SetProcessShutdownParameters.call_args.args == (0x280, 0)


@pytest.mark.skipif(os.name != "nt", reason="native Windows API")
def test_real_windows_registration_query_and_cleanup_on_own_window(qtbot, qapp):
    # No ExitWindows, shutdown.exe or WM_ENDSESSION is sent by this test.
    if qapp.platformName() != "windows":
        pytest.skip("requires the real Windows Qt platform, run separately from offscreen GUI tests")
    window = QMainWindow()
    qtbot.addWidget(window)
    hwnd = int(window.winId())
    api = WindowsRestartAPI()
    registered = False
    try:
        assert api.create(hwnd, "DragonTools Test: laufende Dateiverarbeitung")
        registered = True
        assert api.query(hwnd) == "DragonTools Test: laufende Dateiverarbeitung"
        api.prioritize()
    finally:
        if registered:
            api.destroy(hwnd)
        api.restore_priority()


@pytest.mark.skipif(os.name != "nt", reason="native Windows messages")
def test_real_window_native_query_is_vetoed_before_qt_closes_workers(qtbot, qapp, tmp_path):
    if qapp.platformName() != "windows":
        pytest.skip("requires the real Windows Qt platform")
    clear_user_initiated_shutdown()
    window = QMainWindow()
    qtbot.addWidget(window)
    abort = Mock()
    worker = SimpleNamespace(isRunning=lambda: True, objectName=lambda: "ongoing-conversion",
                             request_abort=abort)
    window._tab_widgets = {"convert": SimpleNamespace(iter_shutdown_workers=lambda: (worker,))}
    diagnostics = RestartGuardDiagnostics(tmp_path/'native-logs')
    instance = WindowsRestartGuard(window, diagnostics=diagnostics)
    instance._timer.stop()
    commit_request = Mock()
    qapp.commitDataRequest.connect(commit_request)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = ctypes.c_ssize_t
    try:
        instance.refresh()
        assert instance._last_status[0] == "aktiv"
        # These are messages to this test's own window, not an OS shutdown.
        for flags in (0, 1, ENDSESSION_CRITICAL):
            result = user32.SendMessageW(int(window.winId()), WM_QUERYENDSESSION, 0, flags)
            assert result == 0
        commit_request.assert_not_called()
        abort.assert_not_called()
        events = _events(instance)
        assert len([row for row in events if row["event"] == "native_query_rejected"]) == 3
        assert instance._api.query(int(window.winId())) == instance._block_reason
    finally:
        qapp.commitDataRequest.disconnect(commit_request)
        instance.dispose()
