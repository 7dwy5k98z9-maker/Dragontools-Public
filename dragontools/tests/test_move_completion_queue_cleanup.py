"""Real Qt completion-dialog regression after an already committed file move."""
from types import SimpleNamespace

import pytest

pytest.importorskip('PyQt6')
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QCheckBox, QLabel, QMessageBox, QProgressBar, QPushButton, QWidget

from dragontools.gui.conversion_result_service import ConversionResultService
from dragontools.gui.conversion_session_state import ConversionSessionState
from dragontools.gui.conversion_start_coordinator import ConversionStartCoordinator
from dragontools.gui.convert_widget_file_queue import ConvertWidgetFileQueueHelper, FileListWidget
from dragontools.gui.convert_widget_queue_management import ConvertWidgetQueueManagementMixin
from dragontools.gui.convert_widget_runtime_ui import ConvertWidgetRuntimeUI
from dragontools.gui.move_regular_lifecycle import RegularMoveLifecycle
from dragontools.gui.run_summary_dialog import RunSummaryDialog


class _Owner(ConvertWidgetQueueManagementMixin, QWidget):
    def _refresh_queue_window(self):
        pass

    def _guard_queue_edit_allowed(self, action):
        return self._runtime_ui.guard_queue_edit_allowed(action)

    def _is_queue_blocking_move_active(self):
        return self._runtime_ui.is_queue_blocking_move_active()

    def _set_start_controls_enabled(self, enabled):
        self._runtime_ui.set_start_controls_enabled(enabled)

    def set_queue_edit_enabled(self, enabled):
        self._runtime_ui.set_queue_edit_enabled(enabled)


def _owner(qtbot, monkeypatch):
    owner = _Owner()
    qtbot.addWidget(owner)
    state = owner._state = ConversionSessionState()
    logs, popups = [], []
    owner._log = lambda message, level='info': logs.append((message, level))
    monkeypatch.setattr(QMessageBox, 'information', lambda *args: popups.append(args))
    monkeypatch.setattr('dragontools.gui.run_summary_dialog.install_persistent_window_geometry', lambda *args: None)
    owner.file_list = FileListWidget(owner)
    ui = SimpleNamespace(file_list=owner.file_list, shut_cb=QCheckBox(owner),
                         eta_lbl=QLabel(owner), file_bar=QProgressBar(owner), progress_bar=QProgressBar(owner))
    for name in ('start_btn', 'dv_remux_btn', 'move_only_btn', 'abort_btn', 'pause_btn', 'curlog_btn'):
        setattr(ui, name, QPushButton(owner))
    for name in ('add_files_btn', 'add_folder_btn', 'remove_btn', 'clear_btn'):
        setattr(owner, name, QPushButton(owner))
    owner._runtime_ui = ConvertWidgetRuntimeUI(parent_widget=owner, state=state, ui=ui,
                                               log=owner._log, refresh_queue=lambda: None)
    owner._file_queue = ConvertWidgetFileQueueHelper(
        parent_widget=owner, file_list=owner.file_list, state=state, log=owner._log,
        guard_queue_edit_allowed=owner._guard_queue_edit_allowed,
        maybe_preflight_new_files=lambda _: None, reset_progress_ui=lambda: None)
    return owner, state, ui, logs, popups


@pytest.mark.parametrize('dialog_action', ['confirm', 'error', 'retry'])
def test_regular_move_modal_completion_clears_missing_source_before_release(qtbot, monkeypatch, tmp_path, dialog_action):
    owner, state, ui, logs, popups = _owner(qtbot, monkeypatch)
    source, destination = tmp_path / 'episode.mkv', tmp_path / 'library' / 'episode.mkv'
    source.write_bytes(b'completed video')
    destination.parent.mkdir()
    owner.file_list.add_path(str(source))
    state.fertig.add(str(source))
    state.file_overrides[str(source)] = {'move': True}
    state.planned_targets[str(source)] = str(destination.parent)
    state.completed_inputs.add(str(source))
    state.run_results[str(source)] = {'input_path': str(source), 'output_path': str(source), 'status': '✅'}
    source.rename(destination)
    failed = tmp_path / 'failed.mkv'
    if dialog_action == 'retry':
        failed.write_bytes(b'input to retry')
        owner.file_list.add_path(str(failed))
        state.run_results[str(failed)] = {'input_path': str(failed), 'status': '❌'}
    worker = SimpleNamespace(isRunning=lambda: True, abort_requested=False, ok_count=1, error_count=0,
                             _move_report_log=[{'source_path': str(source), 'target_path': str(destination), 'ok': True}],
                             log_file_path=None, user_declined_shutdown=False)
    state.move_thread, state.start_reserved = worker, True
    dialog_observations, cleanup_observations = [], []
    actual_exec = RunSummaryDialog.exec
    def finish_dialog(dialog):
        assert state.start_reserved and state.finalization_in_progress
        assert state.move_thread is None
        starter = SimpleNamespace(_state=state, _log=owner._log,
                                  _lifecycle=SimpleNamespace(active_worker=lambda: None))
        assert not ConversionStartCoordinator._claim_start(starter)
        dialog_observations.append(dialog)
        if dialog_action == 'error':
            raise RuntimeError('simulated dialog failure')
        QTimer.singleShot(0, dialog._accept_retry if dialog_action == 'retry' else dialog.accept)
        return actual_exec(dialog)
    monkeypatch.setattr(RunSummaryDialog, 'exec', finish_dialog)
    def clear():
        cleanup_observations.append((state.start_reserved, state.finalization_in_progress))
        owner._clear()
    def requeue(paths):
        assert owner.file_list.count() == 0
        for path in paths:
            owner.file_list.add_path(path)
    service = ConversionResultService(state=state, ui=ui, log=owner._log, start_move=lambda *_: False,
                                      set_start_enabled=owner._set_start_controls_enabled,
                                      set_queue_edit=owner.set_queue_edit_enabled, refresh_queue=lambda: None,
                                      clear=clear, confirm_shutdown=lambda: None, parent_widget=owner,
                                      requeue_files=requeue)
    service._show_replacement_reminders = lambda: None
    lifecycle = RegularMoveLifecycle(state=state, ui=ui, log=owner._log, get_target_paths=lambda: {},
                                     finalize_run=service.finalize_run,
                                     set_start_enabled=owner._set_start_controls_enabled,
                                     set_queue_edit=owner.set_queue_edit_enabled, refresh_queue=lambda: None,
                                     worker_factory=lambda *_: None, on_move_req=lambda *_: None)
    monkeypatch.setattr('dragontools.gui.move_regular_lifecycle.dispatch_after_move', lambda *_: None)
    lifecycle._finish(worker, finished_thread=SimpleNamespace(abort_requested=False, log_file_path=None),
                      moved=True, shutdown=False)
    assert len(dialog_observations) == 1
    assert cleanup_observations == [(True, True)]
    assert popups == []
    assert not any('Warteschlange während Verschieben gesperrt' in message for message, _ in logs)
    assert owner.file_list.get_paths() == ([str(failed)] if dialog_action == 'retry' else [])
    assert not state.fertig and not state.completed_inputs and not state.file_overrides and not state.planned_targets
    assert state.summary_written and not state.finalization_in_progress and not state.start_reserved
    assert state.move_thread is None and worker in state.retired_move_threads
    assert not source.exists() and destination.read_bytes() == b'completed video'
    assert ui.start_btn.isEnabled() and owner.clear_btn.isEnabled()
    lifecycle._finish(worker, finished_thread=None, moved=True, shutdown=False)
    assert len(dialog_observations) == 1 and len(cleanup_observations) == 1


@pytest.mark.parametrize('finalizing,has_move,expected', [
    (False, False, False), (True, False, True), (False, True, False), (True, True, False),
])
def test_queue_guard_distinguishes_start_finalization_and_active_move(qtbot, monkeypatch, finalizing, has_move, expected):
    owner, state, _ui, _logs, popups = _owner(qtbot, monkeypatch)
    state.start_reserved = True
    state.finalization_in_progress = finalizing
    if has_move:
        state.move_thread = SimpleNamespace(isRunning=lambda: True)
    assert owner._guard_queue_edit_allowed('Warteschlange leeren') is expected
    assert len(popups) == (0 if expected else 1)
    assert state.start_reserved
