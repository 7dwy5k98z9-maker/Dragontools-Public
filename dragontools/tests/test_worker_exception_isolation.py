from types import SimpleNamespace

from dragontools.worker import exception_diagnostics as diagnostics
from dragontools.worker import converter_run_loop as run_loop
from dragontools.worker.move_companion_adapter import MoveCompanionAdapterMixin


def test_diagnostics_preserve_original_when_logging_fails(monkeypatch):
    reports = []
    monkeypatch.setattr(diagnostics, 'write_manual_crash_note',
                        lambda reason, **kw: reports.append((reason, kw)) or 'report.txt')
    def broken_log(*args):
        raise OSError('log unavailable')
    try:
        raise ValueError('original failure')
    except Exception as exc:
        assert diagnostics.report_worker_exception(broken_log, 'move failed', exc) == 'report.txt'
    assert 'ValueError: original failure' in reports[0][1]['traceback_text']
    assert 'test_diagnostics_preserve_original' in reports[0][1]['traceback_text']


def test_diagnostics_survive_report_and_traceback_failures(monkeypatch):
    lines = []
    def broken(*args, **kwargs):
        raise RuntimeError('diagnostic failure')
    monkeypatch.setattr(diagnostics.traceback, 'format_exception', broken)
    monkeypatch.setattr(diagnostics, 'write_manual_crash_note', broken)
    try:
        raise TypeError('original failure')
    except Exception as exc:
        assert diagnostics.report_worker_exception(lines.append, 'failed', exc) == ''
    assert any('TypeError: original failure' in line for line in lines)
    assert any('test_diagnostics_survive_report' in line for line in lines)


def test_failed_conversion_does_not_discard_remaining_queue(monkeypatch):
    monkeypatch.setattr(run_loop, 'mark_activity', lambda *a, **kw: None)
    monkeypatch.setattr(run_loop, 'quick_video_resolution', lambda *a: None)
    monkeypatch.setattr(diagnostics, 'write_manual_crash_note', lambda *a, **kw: 'report.txt')
    pending, completed, converted, failures = ['bad.mkv', 'good.mkv'], [], [], []
    class Queue:
        files = pending
        def next_file(self, done):
            return (pending[0], 2) if pending else None
        def complete_current(self, path):
            completed.append(path)
            pending.remove(path)
        def total_after_processed(self, done):
            return done + len(pending)
    def convert(path):
        converted.append(path)
        if path == 'bad.mkv':
            raise RuntimeError('unexpected per-file failure')
    worker = SimpleNamespace(
        _runtime_state=SimpleNamespace(total_count=2, current_idx=0),
        _session_state=SimpleNamespace(suppress_session_header=True, keep_verbose_log=False,
                                      failure_details={}, display_index_by_path={}, display_total=2),
        _services=SimpleNamespace(tools=SimpleNamespace(ffprobe='unused'),
                                  result=SimpleNamespace(fail_unhandled=failures.append)),
        _queue=Queue(), _verbose_logger=None, log_file_path='',
        abort_requested=False, abort_type=None, wait_if_paused=lambda: None,
        log=lambda *a: None, progress=SimpleNamespace(emit=lambda *a: None),
        convert_file=convert,
    )
    run_loop.ConverterRunLoop(worker).execute()
    assert converted == ['bad.mkv', 'good.mkv']
    assert completed == converted
    assert failures == ['bad.mkv']
    assert worker._session_state.failure_details['bad.mkv']['error_report'] == 'report.txt'
    assert worker._session_state.keep_verbose_log


def test_move_failure_remains_local_when_logger_is_broken(monkeypatch):
    monkeypatch.setattr(diagnostics, 'write_manual_crash_note', lambda *a, **kw: 'report.txt')
    def broken_move(*a, **kw):
        raise OSError('share disconnected')
    def broken_log(*a):
        raise RuntimeError('logger failed')
    class Adapter(MoveCompanionAdapterMixin):
        _log = staticmethod(broken_log)
        def _file_service(self):
            return SimpleNamespace(move=broken_move, last_result={'ok': False})
    adapter = Adapter()
    assert adapter._move('source.mkv', 'target') is False
    assert adapter._last_move_result == {'ok': False}


def test_parallel_launch_failure_does_not_discard_next_job(monkeypatch):
    from dragontools.worker.parallel_converter_queue import ParallelConverterQueueMixin
    monkeypatch.setattr(diagnostics, 'write_manual_crash_note', lambda *a, **kw: 'report.txt')
    launches, results = [], []
    worker = SimpleNamespace(
        _pending_files=['bad.mkv', 'good.mkv'], _active_workers=[], parallel_jobs=1,
        _running=True, abort_requested=False, _paused=False, _assigned={},
        _terminal_inputs=set(), _result_state=SimpleNamespace(failure_details={}),
        _synthetic_failures=0, _logger=None,
        file_result=SimpleNamespace(emit=lambda *a: results.append(a)),
    )
    def start(paths):
        launches.extend(paths)
        if paths == ['bad.mkv']:
            raise TypeError('constructor failed')
        worker._active_workers.append(object())
    worker._start_child_worker = start
    ParallelConverterQueueMixin._drain_pending_workers(worker)
    assert launches == ['bad.mkv', 'good.mkv']
    assert worker._synthetic_failures == 1
    assert worker._terminal_inputs == {'bad.mkv'}
    assert worker._result_state.failure_details['bad.mkv']['error_report'] == 'report.txt'
    assert results == [('bad.mkv', 'bad.mkv', '❌')]


def test_postprocess_wait_failure_keeps_diagnostic_log(monkeypatch):
    from dragontools.worker.converter_lifecycle import ConverterLifecycleService
    monkeypatch.setattr(diagnostics, 'write_manual_crash_note', lambda *a, **kw: 'report.txt')
    def fail():
        raise TypeError('wait failed')
    worker = SimpleNamespace(
        _services=SimpleNamespace(postprocess_coordinator=SimpleNamespace(wait_for_all=fail)),
        _session_state=SimpleNamespace(keep_verbose_log=False), log=lambda *a: None,
    )
    ConverterLifecycleService(worker)._wait_for_postprocess_jobs()
    assert worker._session_state.keep_verbose_log


def test_converter_error_still_emits_result_when_verbose_and_report_fail(monkeypatch):
    from dragontools.worker import converter_file_executor as module
    failures, reports = [], []
    def broken(*args, **kwargs):
        raise OSError('diagnostic destination unavailable')
    def workflow(*args):
        raise ValueError('conversion failed')
    monkeypatch.setattr(module, 'configure_optional_file_runtime', lambda *a: None)
    monkeypatch.setattr(module.ConverterFileExecutor, '_check_source_visual_quality', lambda *a: True)
    monkeypatch.setattr(module, 'write_conversion_error_report', broken)
    monkeypatch.setattr(diagnostics, 'write_manual_crash_note',
                        lambda reason, **kw: reports.append(kw) or 'report.txt')
    worker = SimpleNamespace(
        _services=SimpleNamespace(workflow_runner=SimpleNamespace(run=workflow),
                                  result=SimpleNamespace(fail_unhandled=failures.append)),
        _job_state=SimpleNamespace(file_overrides={}, overwrite_original=False, strip_only=False),
        _session_state=SimpleNamespace(keep_verbose_log=False, failure_details={}),
        _temp_state=SimpleNamespace(stderr=''), _logger=SimpleNamespace(log_file=None),
        _verbose_logger=SimpleNamespace(write=broken), log=lambda *a: None,
        emit_file_result=lambda *a: None, emit_file_progress=lambda *a: None,
    )
    assert module.ConverterFileExecutor(worker).execute('bad.mkv') is False
    assert failures == ['bad.mkv']
    assert worker._session_state.keep_verbose_log
    assert 'ValueError: conversion failed' in reports[0]['traceback_text']
