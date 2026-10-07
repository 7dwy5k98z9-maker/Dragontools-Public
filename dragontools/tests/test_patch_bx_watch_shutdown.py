from types import SimpleNamespace

import pytest

from dragontools.gui.watch_folder_controller import WatchFolderController
from dragontools.gui.convert_widget_watch_intake import ConvertWidgetWatchMixin
from dragontools.gui.conversion_worker_lifecycle import ConversionWorkerLifecycle


@pytest.mark.parametrize('thread_stops', [False, True])
def test_stop_blocks_already_queued_scan_and_candidates(thread_stops):
    calls = []
    owner = SimpleNamespace(
        _stopped=False, _timer=SimpleNamespace(stop=lambda: calls.append('timer')),
        _thread=SimpleNamespace(isRunning=lambda: True, requestInterruption=lambda: calls.append('interrupt'),
                                wait=lambda _: thread_stops),
        _status=lambda _: None, _persist_state=lambda: calls.append('persist'),
    )
    assert WatchFolderController.stop(owner, timeout_ms=0) == thread_stops
    assert owner._stopped
    # Must return before touching scanner, settings or dispatch, even if wait timed out.
    WatchFolderController._start_scan(owner)
    WatchFolderController._handle_candidates(owner, [object()])
    WatchFolderController.refresh_settings(owner)
    assert calls[:2] == ['timer', 'interrupt']


@pytest.mark.parametrize('aborted,shutdown', [(True, False), (False, True), (True, True)])
def test_intake_and_delayed_autostart_are_blocked(aborted, shutdown):
    class Converter(ConvertWidgetWatchMixin):
        pass
    owner = Converter()
    owner._state = SimpleNamespace(watch_intake_blocked=aborted)
    owner.shut_cb = SimpleNamespace(isChecked=lambda: shutdown)
    owner._watch_auto_start_eligible = {'queued'}
    assert owner.enqueue_watch_folder_files(['new.mkv']) == []
    owner._watch_maybe_auto_start()
    assert not owner._watch_auto_start_eligible


def test_abort_latches_watch_gate_even_without_current_worker():
    owner = SimpleNamespace(_state=SimpleNamespace(), active_worker=lambda: None)
    ConversionWorkerLifecycle.abort(owner)
    assert owner._state.watch_intake_blocked


def test_close_stops_intake_before_attempting_worker_shutdown(monkeypatch):
    import dragontools.gui.main_window_shutdown as module
    calls = []
    def stop_watch(_window, *, timeout_ms):
        assert timeout_ms == 0
        calls.append('watch')
        return True
    monkeypatch.setattr(module, 'stop_watch_folder_controller', stop_watch)
    monkeypatch.setattr(module, 'shutdown_loaded_widgets',
                        lambda *_args, **_kwargs: calls.append('workers') or SimpleNamespace(ok=False, still_running=['encoder']))
    monkeypatch.setattr(module.QMessageBox, 'warning', lambda *_: None)
    assert not module.prepare_main_window_close(SimpleNamespace(_tab_widgets={}))
    assert calls == ['watch', 'workers']
