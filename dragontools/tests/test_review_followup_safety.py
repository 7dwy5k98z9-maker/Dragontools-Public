from threading import Lock, Event, Barrier, Thread
from types import SimpleNamespace
from unittest.mock import Mock
import subprocess

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication

from dragontools.gui import convert_override_lifecycle as lifecycle
from dragontools.tests.responsibility_checks import structural_risks


@pytest.mark.parametrize('success', [False, True])
def test_real_analyzer_failure_is_not_empty_success(monkeypatch, success):
    from dragontools.core import media_analyzer as analyzer
    monkeypatch.setattr(analyzer, '_run_mediainfo_json', lambda *a: ({}, [], False))
    payload = {'streams': [{'index': 0, 'codec_type': 'video', 'codec_name': 'h264'}]} if success else {}
    monkeypatch.setattr(analyzer, '_run_ffprobe_json', lambda *a: (payload, []))
    monkeypatch.setattr(analyzer, 'apply_hdr10plus_frame_fallback', lambda *a: False)
    monkeypatch.setattr(analyzer, 'log_video_metadata', lambda **kw: None)
    worker = lifecycle._OverrideAnalyzeThread('missing.mkv', SimpleNamespace())
    loaded, failed = Mock(), Mock()
    worker.loaded.connect(loaded)
    worker.failed.connect(failed)
    worker.run()
    assert loaded.call_count == int(success)
    assert failed.call_count == int(not success)
    lifecycle._release_loader(worker)


@pytest.mark.parametrize('action', ['reject', 'accept', 'close'])
@pytest.mark.parametrize('running', [False, True])
def test_all_dialog_exit_paths_abort_loader(action, running):
    app = QApplication.instance() or QApplication([])
    dialog = lifecycle._OverrideDialog()
    worker = Mock(isRunning=Mock(return_value=running))
    dialog._override_loader = worker
    dialog.show()
    getattr(dialog, action)()
    worker.abort.assert_called_once()
    worker.wait.assert_not_called()
    assert dialog._override_loader is None
    dialog.deleteLater()
    app.processEvents()


def test_loader_outlives_dialog_and_suppresses_cancelled_result(monkeypatch):
    app = QApplication.instance() or QApplication([])
    dialog = lifecycle._OverrideDialog()
    worker = lifecycle._OverrideAnalyzeThread('missing', None, dialog)
    assert worker.parent() is None
    assert worker in lifecycle._ACTIVE_LOADERS
    worker.abort()
    loaded = Mock()
    worker.loaded.connect(loaded)
    analyze = Mock()
    monkeypatch.setattr(lifecycle, 'analyze_media', analyze)
    worker.run()
    analyze.assert_not_called()
    loaded.assert_not_called()
    lifecycle._release_loader(worker)
    assert worker not in lifecycle._ACTIVE_LOADERS
    dialog.deleteLater()
    app.processEvents()


def test_cancel_during_real_background_analysis_keeps_thread_alive_safely(monkeypatch):
    app = QApplication.instance() or QApplication([])
    entered, release = Event(), Event()
    def analyze(*args):
        entered.set()
        release.wait(3)
        return SimpleNamespace(analysis_source='ffprobe', video_streams=[object()])
    monkeypatch.setattr(lifecycle, 'analyze_media', analyze)
    dialog = lifecycle._OverrideDialog()
    worker = lifecycle._OverrideAnalyzeThread('file', None, dialog)
    dialog._override_loader = worker
    loaded = Mock()
    worker.loaded.connect(loaded)
    worker.start()
    try:
        assert entered.wait(2)
        dialog.reject()
        assert worker.isRunning()
        assert worker in lifecycle._ACTIVE_LOADERS
        assert worker.parent() is None
    finally:
        release.set()
        assert worker.wait(3000)
    app.processEvents()
    loaded.assert_not_called()
    assert worker not in lifecycle._ACTIVE_LOADERS
    dialog.deleteLater()


@pytest.mark.skipif(__import__('os').name != 'nt', reason='Windows fallback')
@pytest.mark.parametrize('outcome', ['ended', 'timeout', 'kill_error'])
def test_windows_kill_fallback_requires_confirmed_exit(monkeypatch, outcome):
    from dragontools.worker import process_control as subject
    proc = Mock(pid=123, poll=Mock(return_value=None))
    def wait(**kwargs):
        if proc.wait.call_count == 1 or outcome == 'timeout':
            raise subprocess.TimeoutExpired('test', 1)
        proc.poll.return_value = 1
    proc.wait.side_effect = wait
    if outcome == 'kill_error':
        proc.kill.side_effect = OSError('denied')
    worker = SimpleNamespace(_current_process=proc)
    monkeypatch.setattr(subject, '_taskkill_tree', lambda *a, **kw: False)
    result = subject.terminate_process_tree(worker, Lock(), process=proc)
    assert result is (outcome == 'ended')
    assert worker._current_process is (None if result else proc)
    assert proc.wait.call_count == (1 if outcome == 'kill_error' else 2)


@pytest.mark.parametrize('wrapper', ['if True:\n{}', 'try:\n{}\nexcept Exception:\n    pass',
                                    'for x in []:\n{}', 'with context():\n{}'])
def test_architecture_finds_conditional_definitions(wrapper):
    source = 'def heavy(x):\n' + ''.join(f'    if x == {i}: return {i}\n' for i in range(30))
    wrapped = wrapper.format('\n'.join('    ' + line for line in source.splitlines()))
    assert structural_risks(wrapped)['function:heavy'] == 31


def test_queue_rejects_work_after_atomic_exit_decision():
    from dragontools.gui.movie_renamer_job_queue import RenamerResolveJobQueue
    queue = RenamerResolveJobQueue()
    assert queue.take(grace_seconds=0) is None
    assert queue.prepend([(0, 'late.mkv')]) == 0
    assert queue.take(grace_seconds=0) is None


def test_queue_acceptance_and_worker_exit_are_atomic():
    from dragontools.gui.movie_renamer_job_queue import RenamerResolveJobQueue
    for _ in range(30):
        queue = RenamerResolveJobQueue()
        barrier = Barrier(2)
        results = []
        def take():
            barrier.wait()
            results.append(queue.take(grace_seconds=0))
        thread = Thread(target=take)
        thread.start()
        barrier.wait()
        job = (0, 'late.mkv')
        accepted = queue.prepend([job])
        thread.join(2)
        assert not thread.is_alive()
        assert results == ([job] if accepted else [None])


@pytest.mark.parametrize('ended', [False, True])
def test_lifecycle_cleanup_does_not_forget_live_process(monkeypatch, ended):
    from dragontools.worker import tool_process_lifecycle as subject
    monkeypatch.setattr(subject, 'mark_activity', Mock())
    proc = Mock(pid=123, poll=Mock(return_value=0 if ended else None))
    worker = SimpleNamespace(_lock=Lock(), _current_process=proc)
    lifecycle = subject.ProcessLifecycle(['test'], 'test', 1, worker=worker)
    lifecycle.proc = proc
    lifecycle.finish(130)
    assert worker._current_process is (None if ended else proc)


@pytest.mark.parametrize('accepted', [0, 1])
def test_renamer_restarts_rejected_late_job_and_ignores_old_finish(monkeypatch, accepted):
    from dragontools.gui import movie_renamer_resolver as subject
    old = Mock(isRunning=Mock(return_value=True), enqueue_priority=Mock(return_value=accepted))
    new = Mock()
    factory = Mock(return_value=new)
    monkeypatch.setattr(subject, 'MovieRenameResolveThread', factory)
    monkeypatch.setattr(subject, 'config_from_settings', lambda *a, **kw: object())
    view = SimpleNamespace(table=SimpleNamespace(rowCount=lambda: 1), set_busy=Mock(), status_lbl=Mock())
    owner = subject.MovieRenamerResolveCoordinator(None, None, Mock(), view)
    owner.table_controller.find_row_by_path.return_value = 0
    owner.table_controller.row_year_override.return_value = None
    owner.thread = old
    owner.start_jobs([(0, 'late.mkv', '', '', False, None, None)], automatic=False, priority=True)
    if accepted:
        factory.assert_not_called()
        assert owner.thread is old
    else:
        factory.assert_not_called()
        assert owner.thread is old
        # A closed queue does not prove that its native thread has stopped.
        # Preserve that owner, then launch the queued request after completion.
        monkeypatch.setattr(subject.QTimer, 'singleShot', lambda delay, fn: fn())
        old.isRunning.return_value = False
        owner.on_finished(old)
        new.start.assert_called_once()
        assert factory.call_args.args[0][0][1] == 'late.mkv'
        owner.on_finished(old)
        assert owner.thread is new
        assert view.set_busy.call_args.args == (True,)
