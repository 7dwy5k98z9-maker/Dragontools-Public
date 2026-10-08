from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from dragontools.core.conversion_artifacts import ConversionArtifactBundle
from dragontools.core.path_syntax import path_compare_key
from dragontools.gui.conversion_queue_admission import admit_live_queue_paths
from dragontools.gui.conversion_session_state import ConversionSessionState
from dragontools.worker.converter_queue_state import ConverterQueueState
from dragontools.worker.parallel_converter_queue import ParallelConverterQueueMixin
from dragontools.worker.parallel_converter_state import ParallelQueueState, ParallelResultState, ParallelWorkerRegistry
from dragontools.worker.parallel_converter_compat import ParallelConverterCompatibilityMixin
from dragontools.worker.parallel_child_result_coordinator import ParallelChildResultCoordinator
from dragontools.worker.worker_contracts import RemoveFileStatus


SOURCE = r'C:\Media\Episode.mkv'
ALIAS = r'c:\media\EPISODE.MKV'


@pytest.mark.parametrize('deferred', [False, True])
def test_serial_remove_releases_completed_identity_and_skip_marker(deferred):
    queue = ConverterQueueState([SOURCE, 'next.mkv'])
    assert queue.next_file(0)[0] == SOURCE
    queue.skip_files.add(SOURCE)
    if deferred:
        assert queue.remove_file(ALIAS, Mock()) == RemoveFileStatus.PENDING_REMOVE
        assert not queue.add_file(ALIAS, Mock())  # still physically processing
    queue.complete_current(SOURCE)
    if not deferred:
        assert not queue.add_file(ALIAS, Mock())  # retained visible completed row
        assert queue.remove_file(ALIAS, Mock()) == RemoveFileStatus.REMOVED
    assert queue.add_file(ALIAS, Mock())
    assert not queue.add_file(SOURCE, Mock())  # normalized duplicate
    queue.reorder_waiting_files([ALIAS, 'next.mkv'])
    assert path_compare_key(queue.next_file(1)[0]) == path_compare_key(SOURCE)
    assert not queue.skip_files


class _Parallel(ParallelConverterQueueMixin, ParallelConverterCompatibilityMixin):
    def __init__(self, source=SOURCE):
        self._queue_state = ParallelQueueState([source, 'next.mkv'])
        self._queue_state.pending_files = ['next.mkv']
        self._result_state = ParallelResultState()
        self._registry = ParallelWorkerRegistry(self._queue_state, self._result_state)
        self._running, self.abort_requested, self._paused = True, False, True
        self.parallel_jobs = 2
        self._logger = Mock()
        self.file_overrides = {}
        self._emit_aggregate_progress = Mock()


@pytest.mark.parametrize('status', ['✅', '❌', '⚠️', '⏭️'])
def test_parallel_removed_terminal_job_can_be_readded_with_new_options(status):
    thread = _Parallel()
    old = SimpleNamespace(isRunning=lambda: False, remove_file=Mock(return_value=RemoveFileStatus.NOT_FOUND))
    thread._assigned[path_compare_key(SOURCE)] = old
    thread._terminal_inputs.add(SOURCE)
    thread._failure_details[SOURCE] = {'message': 'previous attempt'}
    thread._file_progress_pct[SOURCE] = 100
    thread._queue_state.individually_paused.add(path_compare_key(SOURCE))
    assert thread.remove_file(ALIAS) == RemoveFileStatus.REMOVED
    assert SOURCE not in thread.files and not thread._terminal_inputs
    assert not thread._failure_details and not thread._file_progress_pct
    assert not thread._queue_state.individually_paused
    assert thread.add_file_with_override(ALIAS, {'encoder_profile': 'new settings'})
    assert thread._pending_files.count(ALIAS) == 1
    assert thread.file_overrides[ALIAS]['encoder_profile'] == 'new settings'
    assert not thread.add_file(SOURCE)


def test_parallel_removed_terminal_job_waits_for_physical_child_shutdown():
    thread = _Parallel()
    running = [True]
    old = SimpleNamespace(isRunning=lambda: running[0], files=[SOURCE], _all_input_files=[SOURCE])
    thread._assigned[path_compare_key(SOURCE)] = old
    thread._workers.append(old)
    thread._terminal_inputs.add(SOURCE)
    assert thread.remove_file(SOURCE) == RemoveFileStatus.REMOVED
    assert not thread.add_file(SOURCE)
    assert thread._registry.unreported_child_files(old) == []
    running[0] = False
    assert thread.add_file(SOURCE)


def test_delayed_old_child_result_cannot_finish_new_attempt():
    thread = _Parallel()
    old = SimpleNamespace(isRunning=lambda: False)
    thread._assigned[path_compare_key(SOURCE)] = old
    thread._terminal_inputs.add(SOURCE)
    thread.remove_file(SOURCE)
    thread.add_file(SOURCE)
    new = object()
    thread._assigned[path_compare_key(SOURCE)] = new
    coordinator = ParallelChildResultCoordinator(registry=thread._registry,
        queue_state=thread._queue_state, result_state=thread._result_state)
    emitted = Mock()
    coordinator.on_file_result(old, SOURCE, 'old-output.mkv', '✅', abort_requested=False,
        start_pending_workers=Mock(), emit_file_result=emitted,
        emit_aggregate_progress=Mock(), finish_if_done=Mock())
    emitted.assert_not_called()
    assert not thread._terminal_inputs


def test_stopped_aborted_parallel_child_can_be_removed_before_finished_signal():
    thread = _Parallel()
    thread._assigned[path_compare_key(SOURCE)] = SimpleNamespace(isRunning=lambda: False)
    assert thread.remove_file(SOURCE) == RemoveFileStatus.REMOVED
    assert thread.add_file(SOURCE)


@pytest.mark.parametrize('status', ['✅', '❌', '⚠️', '⏭️'])
@pytest.mark.parametrize('running', [False, True])
def test_gui_readmission_clears_previous_attempt_and_ignores_stopped_worker(status, running):
    state = ConversionSessionState()
    output = r'C:\Output\Episode.mkv'
    state.completed_inputs.add(SOURCE)
    state.run_results[SOURCE] = {'status': status}
    state.artifacts_by_input[SOURCE] = ConversionArtifactBundle(SOURCE, output_path=output, status=status)
    state.fertig.add(output)
    state.sidecar_outputs_by_video[output] = ['old.srt']
    state.pending_remove_paths.add(SOURCE)
    state.file_overrides[ALIAS] = {'encoder_profile': 'changed'}
    state.thread = SimpleNamespace(isRunning=lambda: running,
        add_file_with_override=Mock(return_value=True if running else False))
    queue = SimpleNamespace(state=state, file_list=SimpleNamespace(get_paths=lambda: [ALIAS]),
        maybe_preflight_new_files=Mock(), guard_queue_edit_allowed=lambda action: True, log=Mock())
    rejected, sync = Mock(), Mock()
    assert admit_live_queue_paths(queue, [ALIAS], remove_rejected=rejected, sync_order=sync) == [ALIAS]
    assert not state.completed_inputs and not state.run_results and not state.artifacts_by_input
    assert not state.fertig and not state.sidecar_outputs_by_video and not state.pending_remove_paths
    assert state.file_overrides[ALIAS]['encoder_profile'] == 'changed'
    assert state.thread.add_file_with_override.call_count == int(running)
    if running:
        rejected.assert_called_once_with([])
    else:
        rejected.assert_not_called()


def test_gui_new_attempt_is_not_erased_after_synchronous_worker_result():
    state = ConversionSessionState()
    state.completed_inputs.add(SOURCE)
    state.run_results[SOURCE] = {'status': 'error'}

    def add(path, override):
        state.completed_inputs.add(path)
        state.run_results[path] = {'status': 'ok'}
        return True

    state.thread = SimpleNamespace(isRunning=lambda: True, add_file_with_override=add)
    queue = SimpleNamespace(state=state, file_list=SimpleNamespace(get_paths=lambda: [SOURCE]),
        maybe_preflight_new_files=Mock(), guard_queue_edit_allowed=lambda action: True, log=Mock())
    admit_live_queue_paths(queue, [SOURCE], remove_rejected=Mock(), sync_order=Mock())
    assert state.run_results[SOURCE]['status'] == 'ok'
    assert SOURCE in state.completed_inputs


def test_gui_removal_of_stopped_worker_with_stale_current_path(qtbot):
    from dragontools.gui.convert_widget_file_queue import FileListWidget
    from dragontools.gui.convert_widget_queue_remove import ConvertWidgetQueueRemoveMixin

    rows = FileListWidget()
    qtbot.addWidget(rows)
    rows.add_path(SOURCE)
    state = ConversionSessionState()
    state.thread = SimpleNamespace(isRunning=lambda: False,
        remove_file=Mock(return_value=RemoveFileStatus.CURRENT), reorder_waiting_files=Mock())

    class Helper(ConvertWidgetQueueRemoveMixin):
        file_list = rows
        log = Mock()
        guard_queue_edit_allowed = staticmethod(lambda action: True)
        _sync_total_files = Mock()

    helper = Helper()
    helper.state = state
    helper.remove_paths([SOURCE])
    assert rows.get_paths() == []
    state.thread.remove_file.assert_not_called()
    assert rows.add_path(SOURCE)


def test_deferred_gui_removal_also_releases_parallel_queue_ownership():
    from dragontools.tests.test_conversion_result_service import _service

    thread = _Parallel('input.mkv')
    thread._pending_files = ['next.mkv']
    child = SimpleNamespace(isRunning=lambda: False)
    thread._assigned[path_compare_key('input.mkv')] = child
    thread._terminal_inputs.add('input.mkv')
    service, state, *_ = _service()
    state.thread = thread
    state.pending_remove_paths.add('input.mkv')
    service._set_file_list_item_text = Mock()
    service._ui.file_list = SimpleNamespace(remove_path=Mock())
    service.on_file_result('input.mkv', 'output.mkv', '✅')
    assert 'input.mkv' not in thread.files
    assert thread.add_file('input.mkv')
