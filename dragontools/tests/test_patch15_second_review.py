"""Actual filesystem regressions for move ownership and crash recovery."""
from pathlib import Path
import hashlib
import json
import os

import pytest

from dragontools.core.move_file_service import MoveFileService


def service(*, abort=lambda: False, mode='skip', journal=None):
    return MoveFileService(conflict_mode=mode, log=lambda *a: None,
        wait=lambda: None, abort_immediately=abort, journal=journal)


def pair(tmp_path):
    source = tmp_path / 'source' / 'Episode.mkv'
    source.parent.mkdir()
    source.write_bytes(b'original-video')
    target = tmp_path / 'target'
    target.mkdir()
    return source, target, target / source.name


@pytest.mark.parametrize('directory', [False, True])
def test_immediate_abort_keeps_source_and_target_absent(tmp_path, directory):
    source, target, dest = pair(tmp_path)
    if directory:
        source.unlink()
        source.mkdir()
        (source / 'keep.txt').write_bytes(b'keep')
    ok, result = service(abort=lambda: True).move(str(source), str(target))
    assert not ok and not result['ok']
    assert source.exists() and not dest.exists()


def test_abort_after_copy_verification_keeps_source(tmp_path, monkeypatch):
    from dragontools.core import move_transfer_executor as module
    source, target, dest = pair(tmp_path)
    stopped = []
    monkeypatch.setattr(module.os, 'link', lambda *a, **k: (_ for _ in ()).throw(OSError('EXDEV')))
    verify = module.verify_staged_file_copy
    def verified(src, stage):
        verify(src, stage)
        stopped.append(True)
    monkeypatch.setattr(module, 'verify_staged_file_copy', verified)
    ok, result = service(abort=lambda: bool(stopped)).move(str(source), str(target))
    assert not ok and not result['ok']
    assert source.read_bytes() == b'original-video' and not dest.exists()


def test_source_replaced_after_copy_is_never_deleted(tmp_path, monkeypatch):
    from dragontools.core import move_transfer_executor as module
    source, target, dest = pair(tmp_path)
    monkeypatch.setattr(module.os, 'link', lambda *a, **k: (_ for _ in ()).throw(OSError('EXDEV')))
    verify = module.verify_staged_file_copy
    def verified(src, stage):
        verify(src, stage)
        source.unlink()
        source.write_bytes(b'concurrent-user-source')
    monkeypatch.setattr(module, 'verify_staged_file_copy', verified)
    ok, result = service().move(str(source), str(target))
    assert not ok and not result['ok']
    assert source.read_bytes() == b'concurrent-user-source'
    assert not dest.exists()


def test_foreign_copy_stage_is_neither_overwritten_nor_cleaned(tmp_path, monkeypatch):
    from dragontools.core import move_transfer_executor as module
    source, target, dest = pair(tmp_path)
    foreign = target / 'foreign.__dragontools_partial__fixed'
    foreign.write_bytes(b'user-owned')
    monkeypatch.setattr(module, 'unique_staging_path', lambda *a: foreign)
    monkeypatch.setattr(module.os, 'link', lambda *a, **k: (_ for _ in ()).throw(OSError('EXDEV')))
    ok, _ = service().move(str(source), str(target))
    assert not ok
    assert foreign.read_bytes() == b'user-owned'
    assert source.exists() and not dest.exists()


@pytest.mark.parametrize('stage_foreign', [False, True])
def test_transaction_refuses_late_target_or_stage(tmp_path, monkeypatch, stage_foreign):
    from dragontools.core import move_transaction as module
    source, target, dest = pair(tmp_path)
    backup = target / 'backup'
    tx = module.PathSwapTransaction(source, dest, backup)
    if stage_foreign:
        foreign = target / 'foreign-stage'
        foreign.write_bytes(b'user-stage')
        monkeypatch.setattr(module, 'unique_staging_path', lambda *a: foreign)
        with pytest.raises(FileExistsError):
            tx.stage()
        assert foreign.read_bytes() == b'user-stage'
    else:
        stage = tx.stage()
        dest.write_bytes(b'late-user-target')
        with pytest.raises(FileExistsError):
            tx.commit()
        assert dest.read_bytes() == b'late-user-target'
        assert stage.exists() and not backup.exists()


def test_conflict_backup_collision_preserves_foreign_backup(tmp_path, monkeypatch):
    source, target, dest = pair(tmp_path)
    dest.write_bytes(b'old-target')
    foreign = target / 'foreign-backup'
    foreign.write_bytes(b'user-backup')
    worker = service(mode='overwrite')
    monkeypatch.setattr(worker._conflicts, 'unique_backup_path', lambda *a: foreign)
    ok, _ = worker.move(str(source), str(target))
    assert not ok
    assert dest.read_bytes() == b'old-target'
    assert foreign.read_bytes() == b'user-backup' and source.exists()


@pytest.mark.parametrize('cleanup_pending', [False, True])
def test_recovery_never_uses_unverified_target_to_delete_data(tmp_path, cleanup_pending):
    from dragontools.core.move_journal_recovery import recover_interrupted_backups
    source, target, dest = pair(tmp_path)
    dest.write_bytes(b'foreign-target')
    backup = target / (dest.name + '.__dragontools_backup__old')
    backup.write_bytes(b'original-target-backup')
    if not cleanup_pending:
        source.unlink()
    row = {'status': 'running', 'dest_path': str(dest), 'cleanup_pending': cleanup_pending,
        'backup_pairs': [{'original': str(dest), 'backup': str(backup)}]}
    result = recover_interrupted_backups({'files': {str(source): row}})
    assert result['completed'] == 0 and result['cleaned'] == 0
    assert backup.read_bytes() == b'original-target-backup'
    if cleanup_pending:
        assert source.read_bytes() == b'original-video'
    assert row['status'] == 'running'


@pytest.mark.parametrize('kind', ['job', 'move'])
def test_corrupt_archive_preserves_original_bytes(tmp_path, kind):
    if kind == 'job':
        from dragontools.core.job_journal_storage import archive_job_journal_path as archive
    else:
        from dragontools.core.move_journal_storage import archive_move_journal_path as archive
    path = tmp_path / 'run_broken.json'
    payload = b'{"files": {"valuable-partial-state":'
    path.write_bytes(payload)
    output = archive(path)
    assert (output is not None and output.read_bytes() == payload) or (path.exists() and path.read_bytes() == payload)


@pytest.mark.parametrize('kind', ['job', 'move'])
@pytest.mark.parametrize('field', ['run_id', 'status'])
def test_archive_name_cannot_escape_archive_directory(tmp_path, kind, field):
    if kind == 'job':
        from dragontools.core.job_journal_storage import archive_job_journal_path as archive
    else:
        from dragontools.core.move_journal_storage import archive_move_journal_path as archive
    folder = tmp_path / 'journal'
    folder.mkdir()
    path = folder / 'run_valid.json'
    data = {'run_id': '../escaped' if field == 'run_id' else 'run', 'active': True}
    path.write_text(json.dumps(data), encoding='utf-8')
    output = archive(path, status='../../escape' if field == 'status' else 'ignored')
    assert output is not None and output.resolve().parent == (folder / 'Abgeschlossen').resolve()


def test_path_target_and_unicode_year_survive_journal_and_resume(tmp_path):
    from dragontools.core.move_journal import MoveJournal, build_move_resume_plan
    from dragontools.core.move_routing import MoveRouter
    source = str(tmp_path / 'Ranma.S01E01.mkv')
    base = tmp_path / 'Anime'
    target = base / 'Ranma ½ (2024)' / 'Staffel 01'
    journal = MoveJournal.start(files=[source], planned_targets={source: {'target': target}}, root=tmp_path)
    plan = build_move_resume_plan(journal.data)
    router = MoveRouter(tv_path='', anime_path=str(base), filme_path='', all_video_files=[source],
        planned_target_for=lambda p: plan['planned_targets'].get(p),
        ask=lambda p: pytest.fail('authoritative target was lost'), log=lambda *a: None)
    assert router.route(source) == str(target)


def test_preapproved_episode_does_not_authorize_new_conflict(tmp_path):
    source, target, _ = pair(tmp_path)
    source = source.rename(source.with_name('Serie - S01E03 - New.mkv'))
    old = target / 'Serie - S01E03 - Approved.mkv'
    old.write_bytes(b'approved-old')
    worker = service(mode='overwrite')
    prepared = worker.prepare_move(str(source), str(target))
    late = target / 'Serie - S01E03 - New User File.mkv'
    late.write_bytes(b'late-owner')
    ok, _ = worker.move(str(source), str(target), prepared=prepared)
    assert not ok
    assert old.read_bytes() == b'approved-old' and late.read_bytes() == b'late-owner'
    assert source.exists()


@pytest.mark.parametrize('name', ['../outside.mkv', r'..\outside.mkv', 'C:\\outside.mkv'])
def test_destination_name_cannot_escape_target(tmp_path, name):
    source, target, _ = pair(tmp_path)
    with pytest.raises(ValueError):
        service().prepare_move(str(source), str(target), dest_name=name)
    assert source.exists()


def test_move_archive_failure_keeps_visible_active_journal(tmp_path, monkeypatch):
    from dragontools.core import move_journal as module
    journal = module.MoveJournal.start(files=[str(tmp_path / 'source')], root=tmp_path)
    def fail(*a, **k):
        raise OSError('archive disk full')
    monkeypatch.setattr(journal, '_archive_completed', fail)
    with pytest.raises(OSError):
        journal.finish_run(status='completed', keep_active=False)
    assert module.read_active_move_journal(tmp_path) is not None


def test_sidecar_stem_cannot_consume_neighbor_name(tmp_path):
    from dragontools.core.sidecar_transaction import SidecarCommitTransaction
    neighbor = tmp_path / 'Film2.nfo'
    neighbor.write_bytes(b'user-neighbor')
    tx = SidecarCommitTransaction([str(neighbor)], source_base=tmp_path / 'Film',
        destination_base=tmp_path / 'Other')
    with pytest.raises(ValueError):
        tx.prepare_records()
    assert neighbor.read_bytes() == b'user-neighbor'


def test_cached_filecmp_never_authorizes_source_deletion(tmp_path):
    from dragontools.tests.test_review15_move_safety import _sidecar_service
    source = tmp_path / 'source.nfo'
    dest = tmp_path / 'dest.nfo'
    source.write_bytes(b'original')
    dest.write_bytes(b'original')
    worker = _sidecar_service()
    assert worker._paths_equivalent(source, dest)
    previous = source.stat()
    source.write_bytes(b'user-new')
    os.utime(source, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    assert not worker._paths_equivalent(source, dest)


def test_directory_equivalence_includes_empty_directories(tmp_path):
    from dragontools.tests.test_review15_move_safety import _sidecar_service
    source = tmp_path / 'source'
    dest = tmp_path / 'dest'
    source.mkdir()
    dest.mkdir()
    (source / 'valuable-empty-folder').mkdir()
    assert not _sidecar_service()._paths_equivalent(source, dest)


def test_skip_trickplay_keeps_unverified_source_cache(tmp_path):
    from dragontools.tests.test_review15_move_safety import _sidecar_service
    source = tmp_path / 'source.trickplay'
    dest = tmp_path / 'dest.trickplay'
    source.mkdir()
    dest.mkdir()
    (source / '0001.jpg').write_bytes(b'only-complete-cache')
    ok, result = _sidecar_service(trickplay_mode='skip').move_trickplay(source, dest)
    assert source.exists() and (source / '0001.jpg').read_bytes() == b'only-complete-cache'
    assert ok and result['skipped_conflict']


def test_staged_sidecar_collision_keeps_foreign_stage(tmp_path, monkeypatch):
    from dragontools.tests.test_review15_move_safety import _sidecar_service
    from dragontools.core import move_sidecars as module
    source, target, dest = pair(tmp_path)
    sidecar = source.with_suffix('.nfo')
    sidecar.write_bytes(b'original-nfo')
    foreign = target / 'foreign-stage'
    foreign.write_bytes(b'user-stage')
    monkeypatch.setattr(module, 'unique_staging_path', lambda *a: foreign)
    result = _sidecar_service().stage_before_video(str(source), str(target), [str(sidecar)], dest_video_path=str(dest))
    assert not result['ok']
    assert foreign.read_bytes() == b'user-stage' and sidecar.read_bytes() == b'original-nfo'


@pytest.mark.parametrize('changed', ['source', 'destination'])
def test_replace_recovery_preserves_changed_files(tmp_path, changed):
    from dragontools.core.output_replace import commit_staged_output
    from dragontools.core.replace_journal import recover_active_replace_journals, list_replace_journals
    source = tmp_path / 'movie.mkv'
    stage = tmp_path / 'movie.new.mp4'
    destination = tmp_path / 'movie.mp4'
    source.write_bytes(b'original')
    stage.write_bytes(b'converted')
    commit_staged_output(source=source, staging=stage, destination=destination, journal_root=tmp_path,
        log=lambda *a: None, remove_source=lambda p: (_ for _ in ()).throw(PermissionError('locked')))
    victim = source if changed == 'source' else destination
    victim.unlink()
    victim.write_bytes(b'new-user-file')
    result = recover_active_replace_journals(tmp_path)
    assert result['cleaned_sources'] == 0
    assert source.exists() and victim.read_bytes() == b'new-user-file'
    assert list_replace_journals(tmp_path)


def test_unrelated_final_video_does_not_complete_sidecar_journal(tmp_path):
    from dragontools.core.sidecar_journal import SidecarJournal, recover_active_sidecar_journals
    stage = tmp_path / 'video.new.mkv'
    dest = tmp_path / 'video.mkv'
    stage.write_bytes(b'new-video')
    dest.write_bytes(b'old-or-unrelated-video')
    sidecar = tmp_path / 'video.new.nfo'
    sidecar.write_bytes(b'new-nfo')
    final_sidecar = tmp_path / 'video.nfo'
    journal = SidecarJournal.start(video_staging=stage, video_destination=dest,
        records=[{'source': str(sidecar), 'destination': str(final_sidecar), 'backup': ''}], root=tmp_path)
    stage.unlink()
    result = recover_active_sidecar_journals(tmp_path)
    assert result['completed'] == 0 and journal.path.exists()
    assert sidecar.exists() and not final_sidecar.exists()


@pytest.mark.parametrize('row', [None, {}, {'source': '', 'destination': ''}])
def test_bad_sidecar_rows_do_not_escape_recovery(tmp_path, row):
    from dragontools.core.sidecar_journal import sidecar_journal_dir, recover_active_sidecar_journals
    path = sidecar_journal_dir(tmp_path) / 'sidecar_broken.json'
    path.write_text(json.dumps({'format': 'DragonToolsSidecarJournal', 'format_version': 1,
        'active': True, 'video_committed': True, 'sidecars': [row]}), encoding='utf-8')
    result = recover_active_sidecar_journals(tmp_path)
    assert result['completed'] == 0 and path.exists()


def test_incremental_start_failure_releases_its_flags(monkeypatch):
    from dragontools.tests.test_incremental_move_queue_edit import _controller
    controller, state, *_ = _controller(monkeypatch)
    lifecycle = controller._lifecycle._incremental
    lifecycle._worker_factory = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('start failed'))
    try:
        controller.start_incremental_move(['finished-output.mkv'])
    except RuntimeError:
        pass
    assert not state.incremental_move_active and state.move_thread is None


def test_incremental_double_start_is_rejected(monkeypatch):
    from dragontools.tests.test_incremental_move_queue_edit import _controller
    controller, state, *_ = _controller(monkeypatch)
    controller.start_incremental_move(['finished-output.mkv'])
    first = state.move_thread
    controller.start_incremental_move(['second.mkv'])
    assert state.move_thread is first


def test_incremental_finish_is_once_and_cannot_unlock_new_move(monkeypatch):
    from dragontools.tests.test_incremental_move_queue_edit import _controller
    from types import SimpleNamespace
    controller, state, _, edits, starts, _ = _controller(monkeypatch)
    controller.start_incremental_move(['finished-output.mkv'])
    first = state.move_thread
    first.ok_count = 1
    controller.finish_incremental_move(first)
    initial_count = state.move_ok_count
    replacement = SimpleNamespace(isRunning=lambda: True)
    state.move_thread = replacement
    state.incremental_move_active = True
    edits.clear()
    starts.clear()
    controller.finish_incremental_move(first)
    assert state.move_ok_count == initial_count
    assert state.move_thread is replacement and state.incremental_move_active
    assert edits == starts == []


def test_retired_workers_are_retained_while_running():
    from types import SimpleNamespace
    from dragontools.gui.move_lifecycle_helpers import retire_move_thread
    state = SimpleNamespace(retired_move_threads=[])
    workers = [SimpleNamespace(number=i, isRunning=lambda: True) for i in range(12)]
    for worker in workers:
        retire_move_thread(state, worker)
    assert all(worker in state.retired_move_threads for worker in workers)


def test_job_resume_override_is_detached_from_saved_journal():
    from dragontools.core.job_journal_resume import build_resume_plan
    saved = {'files': {'input.mkv': {'status': 'queued'}},
        'file_overrides': {'input.mkv': {'planned_target': {'target': 'Ranma ½ (2024)'}}}}
    plan = build_resume_plan(saved)
    plan['file_overrides']['input.mkv']['planned_target']['target'] = 'changed'
    assert saved['file_overrides']['input.mkv']['planned_target']['target'] == 'Ranma ½ (2024)'


def test_move_worker_plan_is_detached_from_gui_and_getter(tmp_path):
    from dragontools.worker.move_thread import MoveThread
    source = str(tmp_path / 'Ranma.S01E01.mkv')
    planned = {source: {'target': str(tmp_path / 'Ranma ½ (2024)')}}
    worker = MoveThread([source], '', str(tmp_path), '', planned_targets=planned, move_journal_root=tmp_path)
    expected = planned[source]['target']
    planned[source]['target'] = 'changed-by-gui'
    assert worker._planned_target_for(source)['target'] == expected
    worker._planned_target_for(source)['target'] = 'changed-by-caller'
    assert worker._planned_target_for(source)['target'] == expected


def test_move_journal_case_variant_does_not_create_second_row(tmp_path):
    from dragontools.core.move_journal import MoveJournal
    source = str(tmp_path / 'Episode.mkv')
    journal = MoveJournal.start(files=[source], root=tmp_path)
    journal.set_destination(source.upper(), target_dir=str(tmp_path), dest_path=str(tmp_path / 'final.mkv'))
    assert len(journal.data['files']) == 1


def test_companion_resume_rejects_unverified_final_video(tmp_path):
    from dragontools.core.move_journal_resume import build_move_resume_plan
    source = tmp_path / 'missing.mkv'
    dest = tmp_path / 'unrelated.mkv'
    dest.write_bytes(b'user-file')
    plan = build_move_resume_plan({'files': {str(source): {'status': 'warn',
        'phase': 'sidecars_pending', 'dest_path': str(dest)}}})
    assert plan['files'] == [str(source)]
    assert plan['companion_resume_sources'] == {}


def test_stale_regular_finish_does_not_unlock_replacement(monkeypatch):
    from dragontools.tests.test_incremental_move_queue_edit import _controller
    from types import SimpleNamespace
    controller, state, _, edits, starts, _ = _controller(monkeypatch)
    old = SimpleNamespace(ok_count=0, error_count=0, _move_report_log=[])
    replacement = SimpleNamespace(isRunning=lambda: True)
    state.move_thread = replacement
    state.start_reserved = True
    controller._lifecycle._regular._finish(old, finished_thread=None, moved=False, shutdown=False)
    assert state.move_thread is replacement and state.start_reserved
    assert edits == starts == []


def test_dialog_response_stays_bound_to_its_worker(monkeypatch):
    from types import SimpleNamespace
    from dragontools.gui import move_request_dialogs as module
    first_answers, replacement_answers = [], []
    first = SimpleNamespace(provide_decision=lambda *a: first_answers.append(a))
    replacement = SimpleNamespace(provide_decision=lambda *a: replacement_answers.append(a))
    state = SimpleNamespace(move_thread=first)
    handler = module.MoveRequestDialogHandler(state=state, log=lambda *a: None, parent=None)
    def response(*a, **k):
        state.move_thread = replacement
        return 'TV', True
    monkeypatch.setattr(module.QInputDialog, 'getItem', response)
    handler.handle_series_base_or_folder('request-id', {'bases': [{'label': 'TV', 'path': 'TV'}],
        '_request_worker': first})
    assert first_answers and not replacement_answers


def test_resume_summary_tolerates_invalid_old_row():
    from dragontools.core.job_journal_resume import format_unfinished_job_summary
    assert 'Dateien:' in format_unfinished_job_summary({'files': {'input': None}})


def test_journal_failure_after_link_is_fatal_and_never_retries_copy(tmp_path, monkeypatch):
    from dragontools.core.move_journal import MoveJournal, MoveJournalWriteError
    from dragontools.core import move_transfer_executor as module
    source, target, dest = pair(tmp_path)
    journal = MoveJournal.start(files=[str(source)], root=tmp_path)
    journal.start_file(str(source), target_dir=str(target), dest_path=str(dest))
    links = []
    real_link = module.os.link
    def linked(*a, **k):
        links.append(True)
        return real_link(*a, **k)
    def failed(*a, **k):
        raise MoveJournalWriteError('disk full after installation')
    monkeypatch.setattr(module.os, 'link', linked)
    original_unlink = Path.unlink
    def locked(path, *a, **k):
        if path == source:
            raise PermissionError('source locked')
        return original_unlink(path, *a, **k)
    monkeypatch.setattr(Path, 'unlink', locked)
    monkeypatch.setattr(journal, 'set_cleanup_pending', failed)
    with pytest.raises(MoveJournalWriteError):
        service(journal=journal).move(source, target)
    assert len(links) == 1 and source.exists() and dest.exists()


def test_recovery_does_not_mutate_another_live_process(tmp_path):
    import subprocess
    import sys
    import time
    from dragontools.core.move_journal import recover_active_move_backups
    ready, stop = tmp_path / 'ready', tmp_path / 'stop'
    source, target = tmp_path / 'source.mkv', tmp_path / 'target.mkv'
    backup = tmp_path / 'target.mkv.__dragontools_backup__live'
    source.write_bytes(b'new')
    target.write_bytes(b'old')
    script = f'''
import os,time
from pathlib import Path
from dragontools.core.move_journal import MoveJournal
source, target, backup = map(Path, {list(map(str, [source, target, backup]))!r})
journal=MoveJournal.start(files=[str(source)],root=Path({str(tmp_path)!r}))
journal.start_file(str(source),dest_path=str(target))
journal.set_backups(str(source),[{{'original':str(target),'backup':str(backup)}}])
os.rename(target,backup)
Path({str(ready)!r}).write_text('ready')
while not Path({str(stop)!r}).exists():time.sleep(.02)
'''
    child = subprocess.Popen([sys.executable, '-B', '-c', script], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline and child.poll() is None:
            time.sleep(.02)
        assert ready.exists(), child.communicate(timeout=1) if child.poll() is not None else 'child startup timed out'
        result = recover_active_move_backups(tmp_path)
        assert result['restored'] == 0
        assert backup.read_bytes() == b'old' and not target.exists()
    finally:
        stop.write_text('stop')
        child.communicate(timeout=10)
    result = recover_active_move_backups(tmp_path)
    assert result['restored'] == 1 and target.read_bytes() == b'old'


def test_same_process_recovery_waits_for_active_move(tmp_path):
    from dragontools.core.move_journal import MoveJournal, recover_active_move_backups
    source, target, dest = pair(tmp_path)
    dest.write_bytes(b'old-target')
    journal = MoveJournal.start(files=[str(source)], root=tmp_path)
    journal.start_file(str(source), dest_path=str(dest))
    checked = []
    def callback(_amount):
        result = recover_active_move_backups(tmp_path)
        checked.append(result)
        assert result['cleaned'] == result['restored'] == result['completed'] == 0
    ok, _ = service(journal=journal, mode='overwrite').move(source, target, hook=callback)
    assert ok and len(checked) == 1
    assert checked[0]['cleaned'] == checked[0]['restored'] == checked[0]['completed'] == 0
    assert dest.read_bytes() == b'original-video'


def test_transaction_cannot_overwrite_late_target_after_backup(tmp_path):
    from dragontools.core.move_transaction import PathSwapTransaction, PathTransactionRollbackError
    source, target, dest = pair(tmp_path)
    dest.write_bytes(b'original-old-target')
    backup = target / 'backup'
    tx = PathSwapTransaction(source, dest, backup)
    tx.stage()
    def collision(*a):
        dest.write_bytes(b'late-user-file')
    with pytest.raises(PathTransactionRollbackError):
        tx.commit(on_backup=collision)
    assert dest.read_bytes() == b'late-user-file'
    assert backup.read_bytes() == b'original-old-target'
    assert source.read_bytes() == b'original-video'


def test_replace_rollback_never_moves_changed_destination(tmp_path, monkeypatch):
    from dragontools.core import output_replace as module
    from dragontools.core.replace_journal import ReplaceJournalWriteError
    source, stage, dest = tmp_path / 'movie.mkv', tmp_path / 'new.mp4', tmp_path / 'movie.mp4'
    source.write_bytes(b'original')
    stage.write_bytes(b'converted')
    original = module.ReplaceJournal.set_status
    def status(journal, value, **kwargs):
        if value == 'committed':
            dest.unlink()
            dest.write_bytes(b'user-replacement')
            raise ReplaceJournalWriteError('simulated persistence failure')
        return original(journal, value, **kwargs)
    monkeypatch.setattr(module.ReplaceJournal, 'set_status', status)
    with pytest.raises(OSError):
        module.commit_staged_output(source=source, staging=stage, destination=dest,
            journal_root=tmp_path, log=lambda *a: None)
    assert dest.read_bytes() == b'user-replacement'
    assert source.read_bytes() == b'original'


def test_sidecar_rollback_never_moves_changed_destination(tmp_path):
    from dragontools.core.sidecar_transaction import SidecarCommitTransaction, SidecarCommitError
    source = tmp_path / 'video.new.nfo'
    dest = tmp_path / 'video.nfo'
    source.write_bytes(b'new-nfo')
    dest.write_bytes(b'old-nfo')
    tx = SidecarCommitTransaction([str(source)], source_base=tmp_path / 'video.new',
        destination_base=tmp_path / 'video')
    tx.commit()
    dest.unlink()
    dest.write_bytes(b'user-after-commit')
    with pytest.raises(SidecarCommitError):
        tx.rollback()
    assert dest.read_bytes() == b'user-after-commit'
    assert tx.backup_pairs[0][1].read_bytes() == b'old-nfo'


def test_legacy_target_dir_survives_authoritative_routing(tmp_path):
    from dragontools.core.move_routing import MoveRouter
    base = tmp_path / 'Anime'
    target = base / 'Ranma ½ (2024)' / 'Staffel 01'
    router = MoveRouter(tv_path='', anime_path=str(base), filme_path='', all_video_files=[],
        planned_target_for=lambda p: {'target_dir': str(target)},
        ask=lambda p: pytest.fail('must preserve the journal target'), log=lambda *a: None)
    assert router.route('Ranma.S01E01.mkv') == str(target)


def test_missing_sidecar_needs_a_recorded_commit(tmp_path):
    from dragontools.tests.test_review15_move_safety import _sidecar_service
    video = tmp_path / 'video.mkv'
    source = tmp_path / 'video.nfo'
    target = tmp_path / 'target'
    target.mkdir()
    (target / source.name).write_bytes(b'unrelated-user-nfo')
    result = _sidecar_service().move_sidecars(str(video), str(target), [str(source)])
    assert not result['ok'] and result['failed'] == 1
    assert (target / source.name).read_bytes() == b'unrelated-user-nfo'


def test_staging_receipt_survives_service_handoff(tmp_path):
    from dragontools.tests.test_review15_move_safety import _sidecar_service
    source, target, dest = pair(tmp_path)
    sidecar = source.with_suffix('.nfo')
    sidecar.write_bytes(b'original-nfo')
    stage = _sidecar_service().stage_before_video(str(source), str(target), [str(sidecar)], dest_video_path=str(dest))
    _sidecar_service().rollback_stage(stage)
    assert sidecar.exists() and not (target / sidecar.name).exists()


def test_changed_source_invalidates_prepared_video(tmp_path):
    source, target, dest = pair(tmp_path)
    worker = service()
    prepared = worker.prepare_move(source, target)
    source.unlink()
    source.write_bytes(b'user-replacement-after-planning')
    ok, result = worker.move(source, target, prepared=prepared)
    assert not ok and not result['ok']
    assert source.read_bytes() == b'user-replacement-after-planning' and not dest.exists()


@pytest.mark.parametrize('changed', [False, True])
def test_companion_resume_rechecks_committed_video_before_worker_commit(tmp_path, changed):
    from dragontools.core.move_journal import MoveJournal, build_move_resume_plan
    import hashlib
    from dragontools.worker.move_thread import MoveThread
    source, target, dest = pair(tmp_path)
    os.rename(source, dest)
    journal = MoveJournal.start(files=[str(source)], root=tmp_path,
        planned_targets={str(source): {'target': str(target)}})
    info = dest.stat()
    proof = {'identity': [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns],
        'content': hashlib.sha256(b'file\0' + dest.read_bytes()).hexdigest()}
    journal.data['files'][str(source)].update(status='warn', phase='sidecars_pending',
        dest_path=str(dest), target_dir=str(target),
        commit_proof={'destination': proof})
    plan = build_move_resume_plan(journal.data)
    if changed:
        dest.unlink()
        dest.write_bytes(b'foreign-user-video')
    worker = MoveThread(plan['files'], '', '', str(tmp_path), planned_targets=plan['planned_targets'],
        companion_resume_sources=plan['companion_resume_sources'],
        move_journal_root=tmp_path, log_file_path=str(tmp_path / 'log.txt'))
    commits = []
    worker._logger.long_log_file = tmp_path / 'long.log'
    worker._record_media_library_move = lambda *a: commits.append(a)
    worker.run()
    assert worker.ok_count == (0 if changed else 1)
    assert worker.error_count == (1 if changed else 0)
    assert bool(commits) is (not changed)
    assert dest.read_bytes() == (b'foreign-user-video' if changed else b'original-video')


def test_same_process_recovery_waits_during_companion_stage(tmp_path):
    from dragontools.core.move_journal import recover_active_move_backups, read_active_move_journal, archive_move_journal_path
    from dragontools.worker.move_thread import MoveThread
    source, target, dest = pair(tmp_path)
    worker = MoveThread([str(source)], '', '', str(tmp_path),
        planned_targets={str(source): {'target': str(target)}},
        move_journal_root=tmp_path, log_file_path=str(tmp_path / 'log.txt'))
    checked = []
    worker._logger.long_log_file = tmp_path / 'long.log'
    def stage(*a):
        recovery = recover_active_move_backups(tmp_path)
        recovery['visible'] = read_active_move_journal(tmp_path)
        try:
            archive_move_journal_path(worker._move_journal.path)
            recovery['archived_live'] = True
        except OSError:
            recovery['archived_live'] = False
        checked.append(recovery)
        return {'ok': True, 'staged_paths': [], 'protected_paths': []}
    worker._stage_sidecars_before_video = stage
    worker._record_media_library_move = lambda *a: None
    worker.run()
    assert worker.ok_count == 1 and dest.read_bytes() == b'original-video'
    assert len(checked) == 1 and checked[0]['kept'] == 1
    assert checked[0]['visible'] is None and not checked[0]['archived_live']


def receipt(path):
    info = path.stat()
    return {'identity': [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns],
        'content': hashlib.sha256(b'file\0' + path.read_bytes()).hexdigest()}


@pytest.mark.parametrize('changed', [False, True])
def test_partial_companion_resume_preserves_existing_commit_proofs(tmp_path, changed):
    from dragontools.core.move_journal import MoveJournal, build_move_resume_plan, read_active_move_journal
    from dragontools.worker.move_thread import MoveThread
    source, target, dest = pair(tmp_path)
    nfo = source.with_suffix('.nfo')
    dest_nfo = target / 'movie.nfo'
    subtitle = source.with_suffix('.de.srt')
    dest_nfo.write_bytes(b'<movie/>')
    subtitle.write_bytes(b'original-subtitle')
    os.rename(source, dest)
    journal = MoveJournal.start(files=[str(source)], root=tmp_path,
        planned_targets={str(source): {'target': str(target)}},
        sidecar_outputs_by_video={str(source): [str(nfo), str(subtitle)]})
    journal.data['files'][str(source)].update(status='warn', phase='sidecars_pending',
        dest_path=str(dest), target_dir=str(target), commit_proof={'destination': receipt(dest)},
        companion_proofs={str(nfo): {'destination': str(dest_nfo), 'receipt': receipt(dest_nfo)}})
    plan = build_move_resume_plan(journal.data)
    if changed:
        dest_nfo.unlink()
        dest_nfo.write_bytes(b'foreign-user-nfo')
    worker = MoveThread(plan['files'], '', '', str(tmp_path),
        planned_targets=plan['planned_targets'], companion_resume_sources=plan['companion_resume_sources'],
        sidecar_outputs_by_video=plan['sidecar_outputs_by_video'],
        move_journal_root=tmp_path, log_file_path=str(tmp_path / 'log.txt'))
    worker._logger.long_log_file = tmp_path / 'long.log'
    commits = []
    worker._read_nfo_movie_target_name = lambda: 'movie.nfo'
    worker._record_media_library_move = lambda *a: commits.append(a)
    visible = []
    worker._archive_superseded_journal = lambda: visible.append(
        (read_active_move_journal(tmp_path) or {}).get('_journal_path') == str(worker._move_journal.path))
    worker.run()
    assert visible == [False]
    assert worker.ok_count == (0 if changed else 1)
    assert worker.error_count == (1 if changed else 0)
    assert bool(commits) is (not changed)
    assert dest.read_bytes() == b'original-video'
    assert dest_nfo.read_bytes() == (b'foreign-user-nfo' if changed else b'<movie/>')
    assert dest.with_suffix('.de.srt').read_bytes() == b'original-subtitle'
    assert worker._move_journal.path.exists() is changed
