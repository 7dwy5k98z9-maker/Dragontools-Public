"""Regression coverage for the 9.8.3 result/process/commit boundaries."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event, Lock
from types import SimpleNamespace
import subprocess
import sys

import pytest

from dragontools.core.output_replace import commit_staged_output
from dragontools.worker.worker_result_service import WorkerConversionResultService
from dragontools.worker.postprocess_async import AsyncPostProcessCoordinator
from dragontools.worker.workflow_output_commit import WorkflowOutputCommitCoordinator
from dragontools.worker.workflow_engine import WorkflowContext
from dragontools.worker.tool_process_lifecycle import ProcessLifecycle
from dragontools.worker.job_process_owner import JobProcessOwner


def result_service(events, event_emit=lambda *_: None):
    return WorkerConversionResultService(
        logger=SimpleNamespace(info=lambda *a: None, warn=lambda *a: None),
        runtime_state=SimpleNamespace(fehlgeschlagen=0), overwrite_original=True,
        event_emit=event_emit, file_progress_emit=lambda *a: None,
        file_result_emit=lambda *a: events.append(a), log=lambda *a: None, failure_details={},
    )


@pytest.mark.parametrize('status', ['⚠️', '❌', '⏭️'])
def test_terminal_failure_cannot_become_success(status):
    events = []
    service = result_service(events)
    service.emit_file_result('in', 'out', status)
    service.emit_file_result('in', 'out', '✅')
    service.emit_file_result('in', 'out', '🧩')
    assert [e[2] for e in events] == [status]


def test_concurrent_success_and_error_always_end_in_error():
    for _ in range(30):
        events = []
        service = result_service(events)
        barrier = Barrier(2)
        def send(status):
            barrier.wait()
            service.emit_file_result('in', 'out', status)
        with ThreadPoolExecutor(2) as pool:
            list(pool.map(send, ['✅', '❌']))
        assert events[-1][2] == '❌'


def test_reentrant_error_never_delivers_stale_success():
    events = []
    def callback(event):
        if event.status == '✅':
            service.emit_file_result('in', 'out', '❌')
    service = result_service(events, callback)
    service.emit_file_result('in', 'out', '✅')
    assert [e[2] for e in events] == ['❌']


def test_cleanup_pending_does_not_schedule_success_callback(tmp_path):
    events, submissions = [], []
    result = result_service(events)
    post = SimpleNamespace(run_result=lambda **kw: SimpleNamespace(created_paths=[], items=[]))
    coordinator = WorkflowOutputCommitCoordinator(
        replace_service=SimpleNamespace(replace=lambda **kw: kw['output_path'],
            cleanup_pending=lambda p: True, was_blocked=lambda p: False,
            last_cleanup_message='original locked'),
        logger=SimpleNamespace(warn=lambda *a: None), result_service=result,
        sidecar_outputs={}, postprocess_outputs={}, postprocess_service=post,
        postprocess_coordinator=SimpleNamespace(submit=lambda **kw: submissions.append(kw)),
    )
    ctx = WorkflowContext(input_path='in', output_path=str(tmp_path/'out.mp4'), container='mp4')
    coordinator.replace(ctx)
    result.finalize_cleanup_pending(ctx)
    assert not submissions and not ctx.postprocess_pending
    assert events[-1][2] == '⚠️'


def test_late_async_callback_preserves_error():
    release = Event()
    events = []
    service = result_service(events)
    def run(**kw):
        assert release.wait(5)
        return SimpleNamespace(created_paths=[], items=[])
    coordinator = AsyncPostProcessCoordinator(settings=None, tools=None, log=lambda *a: None,
        service_factory=lambda: SimpleNamespace(run_result=run))
    try:
        coordinator.submit(input_path='in', output_path='out', existing_sidecars=[],
            sidecar_outputs={}, postprocess_outputs={}, result_service=service)
        service.emit_file_result('in', 'out', '❌')
    finally:
        release.set()
        coordinator.wait_for_all()
    assert [e[2] for e in events] == ['🧩', '❌']


@pytest.mark.parametrize('terminal', ['⚠️', '❌', '⏭️'])
def test_gui_rejects_late_success_before_any_move_or_ui_mutation(terminal):
    from dragontools.core.conversion_artifacts import ConversionArtifactBundle
    from dragontools.gui.conversion_result_file_events import ConversionResultFileEventsMixin
    class GUI(ConversionResultFileEventsMixin):
        def _set_file_list_item_text(self, *a):
            raise AssertionError('stale result reached GUI')
    gui = GUI()
    gui._state = SimpleNamespace(artifacts_by_input={
        'in': ConversionArtifactBundle('in', 'out', status=terminal)}, fertig=set())
    gui.on_file_result('in', 'out', '✅')
    assert not gui._state.fertig


def test_lifecycle_termination_uses_own_process(monkeypatch):
    import dragontools.worker.tool_process_lifecycle as module
    parent = SimpleNamespace(_lock=Lock(), _current_process=None)
    processes = [SimpleNamespace(pid=n, poll=lambda: None) for n in (111,222)]
    killed = []
    monkeypatch.setattr(module, 'mark_activity', lambda *a, **kw: None)
    monkeypatch.setattr(module, 'terminate_process_tree', lambda *a, **kw: killed.append(kw['process']))
    lives = [ProcessLifecycle([str(i)], str(i), 1, worker=parent) for i in range(2)]
    for life, proc in zip(lives, processes):
        life.register(proc)
    lives[0]._terminate()
    assert killed == processes[:1]
    assert parent._current_process is processes[1]


def test_job_owner_cancellation_and_process_slots_are_isolated():
    parent = SimpleNamespace(abort_requested=False, abort_type=None)
    a, b = JobProcessOwner(parent), JobProcessOwner(parent)
    a._current_process = object()
    a.request_abort()
    assert a.abort_requested and not b.abort_requested and not parent.abort_requested
    assert b._current_process is None and a._lock is not b._lock
    parent.abort_requested, parent.abort_type = True, 'sofort'
    assert b.abort_requested and b.abort_type == 'sofort'


def test_real_child_cancel_does_not_kill_sibling(monkeypatch):
    import dragontools.worker.tool_process_lifecycle as module
    monkeypatch.setattr(module, 'mark_activity', lambda *a, **kw: None)
    parent = SimpleNamespace(_lock=Lock(), _current_process=None)
    kwargs = {'start_new_session': True} if sys.platform != 'win32' else {'creationflags': subprocess.CREATE_NO_WINDOW}
    procs = [subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], **kwargs) for _ in range(2)]
    try:
        lives = [ProcessLifecycle(['python'], 'test', 1, worker=parent) for _ in procs]
        for life, proc in zip(lives, procs):
            life.register(proc)
        lives[0]._terminate()
        assert procs[0].poll() is not None
        assert procs[1].poll() is None
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)


@pytest.mark.parametrize('same_path', [True, False])
def test_abort_after_journal_preparation_never_installs(tmp_path, monkeypatch, same_path):
    from dragontools.core.replace_journal import ReplaceJournal
    source, stage = tmp_path/'in.mkv', tmp_path/'stage.mp4'
    source.write_bytes(b'original')
    stage.write_bytes(b'new')
    dest = source if same_path else tmp_path/'in.mp4'
    aborted = [False]
    original = ReplaceJournal.start
    def start(**kw):
        journal = original(**kw)
        aborted[0] = True
        return journal
    monkeypatch.setattr(ReplaceJournal, 'start', start)
    with pytest.raises(RuntimeError, match='Abgebrochen'):
        commit_staged_output(source=source, staging=stage, destination=dest,
            log=lambda *a: None, journal_root=tmp_path, abort_check=lambda: aborted[0])
    assert source.read_bytes() == b'original'
    assert stage.read_bytes() == b'new'


def test_mp4_abort_after_sidecar_commit_restores_old_sidecar(tmp_path):
    from dragontools.worker.mp4_remux_file_service import MP4RemuxFileService
    from dragontools.core.sidecar_transaction import SidecarCommitTransaction
    source, stage, dest = (tmp_path/n for n in ('in.mkv','stage.mp4','in.mp4'))
    old_sub, new_sub = tmp_path/'in.de.srt', tmp_path/'stage.de.srt'
    source.write_bytes(b'original')
    stage.write_bytes(b'converted')
    old_sub.write_text('user subtitle')
    new_sub.write_text('new subtitle')
    aborted = [False]
    def commit(paths, **kw):
        tx = SidecarCommitTransaction(paths, source_base=stage.with_suffix(''), destination_base=dest.with_suffix(''))
        tx.commit()
        aborted[0] = True
        return tx
    service = MP4RemuxFileService(
        planner=SimpleNamespace(build=lambda *a: SimpleNamespace(source=source, staging=stage,
            destination=dest, duration_s=1, command=['ffmpeg']), video_compatibility=lambda _: (True,'ok')),
        logger=SimpleNamespace(file_start=lambda *a, **kw: None), log=lambda *a: None,
        run_ffmpeg=lambda *a: 0, export_sidecars=lambda *a, **kw: SimpleNamespace(exported_paths=[str(new_sub)], complete=True),
        commit_sidecars=commit, cleanup_sidecars=lambda paths: [Path(p).unlink(missing_ok=True) for p in paths],
        abort_requested=lambda: aborted[0], emit_file_result=lambda *a: None,
        emit_file_progress=lambda *a: None, export_subtitles=True, ignore_subtitles=False,
    )
    assert not service.remux(str(source),str(dest),SimpleNamespace(analysis_source='test'),
        current_index=1,total_files=1,user_abort_error=RuntimeError)
    assert source.read_bytes() == b'original' and not dest.exists()
    assert old_sub.read_text() == 'user subtitle'
    assert not stage.exists() and not new_sub.exists()


@pytest.mark.parametrize('same_path', [True, False])
def test_abort_during_first_rename_keeps_original(tmp_path, monkeypatch, same_path):
    import dragontools.core.output_replace as module
    source, stage = tmp_path/'in.mkv', tmp_path/'stage.mp4'
    source.write_bytes(b'original')
    stage.write_bytes(b'converted')
    dest = source if same_path else tmp_path/'in.mp4'
    aborted = [False]
    original_replace = module.os.replace
    def replace(src, dst):
        original_replace(src, dst)
        if Path(src) == (source if same_path else stage):
            aborted[0] = True
    monkeypatch.setattr(module.os, 'replace', replace)
    with pytest.raises(RuntimeError, match='Abgebrochen'):
        commit_staged_output(source=source, staging=stage, destination=dest,
            log=lambda *a: None, journal_root=tmp_path, abort_check=lambda: aborted[0])
    assert source.read_bytes() == b'original'
    assert stage.read_bytes() == b'converted'


def test_pause_uses_lifecycle_process_not_latest_worker_slot(monkeypatch):
    import dragontools.worker.tool_process_lifecycle as module
    seen = []
    worker = SimpleNamespace(_lock=Lock(), _paused=True, _current_process=object())
    life = ProcessLifecycle(['tool'], 'tool', 1, worker=worker)
    life.proc = object()
    monkeypatch.setattr(module, 'wait_while_paused', lambda *a, **kw: seen.append(kw['process']))
    life.handle_pause()
    assert seen == [life.proc] and life.proc is not worker._current_process


def test_same_path_abort_after_install_restores_backup(tmp_path, monkeypatch):
    import dragontools.core.output_replace as module
    source, stage = tmp_path/'in.mp4', tmp_path/'stage.mp4'
    source.write_bytes(b'original')
    stage.write_bytes(b'converted')
    aborted = [False]
    original_status = module.ReplaceJournal.set_status
    def set_status(self, status, **kwargs):
        original_status(self, status, **kwargs)
        if status == 'committed':
            aborted[0]=True
    monkeypatch.setattr(module.ReplaceJournal,'set_status',set_status)
    with pytest.raises(RuntimeError,match='Abgebrochen'):
        commit_staged_output(source=source,staging=stage,destination=source,
            journal_root=tmp_path,log=lambda *a: None,abort_check=lambda:aborted[0])
    assert source.read_bytes()==b'original'
    assert stage.read_bytes()==b'converted'
