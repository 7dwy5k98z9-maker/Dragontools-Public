import io
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryFile
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import Mock
import tracemalloc
import weakref
import gc

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication

from dragontools.worker.packet_snapshot import read_snapshot
from dragontools.worker.tool_output_buffer import ToolOutputBuffer
from dragontools.worker.tool_runner import run_tool


@pytest.mark.parametrize('payload', ['', '{}', '[]', '{"packets":[],"streams":[],}',
    '{"packets":[{}],"streams":[]}', '{"packets":[],"packets":[],"streams":[]}',
    '{"packets":[],"streams":[]} garbage', '{"packets":[',
    '{"packets":[],"streams":[{"index":true,"codec_type":"video"}]}'])
def test_malformed_packet_documents_fail_closed(payload):
    with pytest.raises((ValueError, TypeError)):
        read_snapshot(io.StringIO(payload))


def _write_packets(output, count):
    output.write('{"packets":[')
    record = json.dumps({'stream_index': 0, 'data_hash': 'SHA256:' + 'a' * 64,
                         'pts_time': '0', 'duration_time': '0.04'})
    for i in range(count):
        output.write((',' if i else '') + record)
    output.write('],"streams":[{"index":0,"codec_type":"video"}]}')
    output.seek(0)


def test_packet_memory_is_bounded_and_completed_snapshots_have_no_lists():
    peaks = []
    for count in (1000, 50000):
        with TemporaryFile(mode='w+', encoding='utf-8') as output:
            _write_packets(output, count)
            tracemalloc.start()
            try:
                result = read_snapshot(output)
                peaks.append(tracemalloc.get_traced_memory()[1])
            finally:
                tracemalloc.stop()
        assert result[0].packet_count == count
        assert isinstance(result[0].hashes, str) and len(result[0].hashes) == 64
    assert peaks[1] < 2 * 1024 * 1024
    assert peaks[1] - peaks[0] < 512 * 1024


@pytest.mark.parametrize('limit', [None, 0, -1, True, '100'])
def test_invalid_output_limits_are_rejected(limit):
    with pytest.raises(ValueError):
        ToolOutputBuffer(limit)


def test_output_buffer_is_bounded_and_release_discards_future_output():
    buffer = ToolOutputBuffer(1024)
    for _ in range(10000):
        buffer.append('x' * 100)
    assert buffer.size <= 1024 and buffer.truncated
    buffer.release()
    buffer.append('late output')
    assert not buffer.lines and buffer.size == 0 and buffer.text() == ''


@pytest.mark.parametrize('command', [None, '', 'ffprobe', [], [''], ['  ']])
def test_invalid_commands_are_rejected_before_start(command):
    with pytest.raises(ValueError):
        run_tool(command)


def test_tool_can_write_large_output_directly_to_file(monkeypatch):
    monkeypatch.setattr('dragontools.worker.tool_process_lifecycle.mark_activity', lambda *a, **kw: None)
    with TemporaryFile(mode='w+', encoding='utf-8') as output:
        result = run_tool([sys.executable, '-c', 'import sys; sys.stdout.write("x"*10000000)'],
                          stdout_file=output, timeout_s=15)
        assert result.ok and result.stdout == ''
        assert output.tell() == 10000000


def test_pipe_cleanup_is_bounded_even_with_blocked_reader():
    from dragontools.worker.tool_process_lifecycle import close_process_streams
    readfd, writefd = os.pipe()
    stream = os.fdopen(readfd, 'r')
    entered, cleaned = Event(), Event()
    def read():
        entered.set()
        stream.readline()
    reader = Thread(target=read)
    reader.start()
    entered.wait(1)
    Event().wait(.05)
    def cleanup():
        close_process_streams(SimpleNamespace(stdout=stream, stderr=None))
        cleaned.set()
    closer = Thread(target=cleanup)
    closer.start()
    try:
        assert cleaned.wait(1), 'Cleanup waited indefinitely for reader lock'
    finally:
        os.write(writefd, b'end\n')
        os.close(writefd)
        reader.join(2)
        closer.join(2)


def test_main_window_shutdown_includes_cancelled_dialog_analysis(monkeypatch):
    from dragontools.gui import convert_override_lifecycle as loader_module
    from dragontools.gui import main_window_shutdown as subject
    app = QApplication.instance() or QApplication([])
    entered, release = Event(), Event()
    def analyze(*args):
        entered.set()
        release.wait(3)
        return SimpleNamespace()
    monkeypatch.setattr(loader_module, 'analyze_media', analyze)
    monkeypatch.setattr(subject.QMessageBox, 'warning', Mock())
    for name in ('stop_metadata_action_thread', 'stop_watch_folder_controller', 'stop_jellyfin_workers'):
        monkeypatch.setattr(subject, name, lambda *a, **kw: True)
    worker = loader_module._OverrideAnalyzeThread('file', None)
    worker.start()
    try:
        assert entered.wait(1)
        assert subject.prepare_main_window_close(SimpleNamespace(_tab_widgets={}), timeout_ms=1) is False
        assert worker._abort is True
    finally:
        release.set()
        assert worker.wait(3000)
        app.processEvents()
    assert subject.prepare_main_window_close(SimpleNamespace(_tab_widgets={}), timeout_ms=1)


def test_renamer_error_closes_queue_before_notifying(monkeypatch):
    from dragontools.gui import movie_renamer_resolver as subject
    monkeypatch.setattr(subject, 'parse_movie_release_name', lambda *a: SimpleNamespace(is_probable_series=False))
    monkeypatch.setattr(subject, 'client_from_config', Mock(side_effect=RuntimeError('provider unavailable')))
    worker = subject.MovieRenameResolveThread([(0, 'a.mkv'), (1, 'b.mkv')], None)
    accepted = []
    worker.failed.connect(lambda message: accepted.append(worker.enqueue_priority([(2, 'c.mkv')])))
    worker.run()
    assert accepted == [0]
    assert worker._jobs.take(grace_seconds=0) is None
    assert not worker._jobs._jobs


def test_conditional_class_methods_are_counted():
    from dragontools.tests.responsibility_checks import structural_risks
    source = 'class Many:\n    if True:\n'
    for i in range(10):
        source += f'        def task{i}(self, x):\n'
        source += ''.join(f'            if x == {j}: return {j}\n' for j in range(6))
    assert structural_risks(source)['class-behaviors:Many'] == 10


@pytest.mark.parametrize('status', ['✅', '❌', '⚠️', '⏭️'])
def test_terminal_file_releases_analysis_objects(status):
    from dragontools.tests.test_conversion_result_service import _service
    class Analysis:
        pass
    service, state, *_ = _service()
    service._set_file_list_item_text = Mock()
    item = Analysis()
    ref = weakref.ref(item)
    state.preflight_rows_by_path['file'] = {'tracks': [item]}
    state.active_file_progress['file'] = 80
    state.active_file_eta['file'] = 10
    del item
    service.on_file_result('file', 'out', status)
    gc.collect()
    assert ref() is None
    assert 'file' not in state.active_file_progress and 'file' not in state.active_file_eta
    assert 'file' in state.run_results  # Required report/retry information survives.


def test_clear_all_releases_preflight_cache():
    from dragontools.gui.conversion_session_state import ConversionSessionState
    state = ConversionSessionState()
    state.preflight_rows_by_path['old'] = {'tracks': list(range(1000))}
    state.clear_all()
    assert not state.preflight_rows_by_path


def test_late_progress_cannot_recreate_completed_file_state():
    from dragontools.gui.conversion_progress_presenter import ConversionProgressPresenter
    state = SimpleNamespace(completed_inputs={'done'}, active_file_progress={}, active_file_eta={})
    presenter = SimpleNamespace(_state=state)
    ConversionProgressPresenter.on_file_progress(presenter, 'done', 25, 50)
    assert not state.active_file_progress and not state.active_file_eta


def test_long_output_line_is_not_corrupted_by_bounded_reads(monkeypatch):
    monkeypatch.setattr('dragontools.worker.tool_process_lifecycle.mark_activity', lambda *a, **kw: None)
    result = run_tool([sys.executable, '-c', 'print("x"*200000)'], timeout_s=10)
    assert result.ok and result.stdout == 'x' * 200000


def test_many_callbacks_are_drained_without_loss(monkeypatch):
    monkeypatch.setattr('dragontools.worker.tool_process_lifecycle.mark_activity', lambda *a, **kw: None)
    seen = []
    result = run_tool([sys.executable, '-c', 'for i in range(2000): print(i)'], stdout_line=seen.append, timeout_s=10)
    assert result.ok
    assert seen == [str(i) for i in range(2000)]


@pytest.mark.parametrize('index', [None, True, -1, 1.5, 'bad', 65536])
def test_invalid_packet_indices_fail_closed(index):
    payload = {'streams': [{'index': 0, 'codec_type': 'video'}],
               'packets': [{'stream_index': index, 'data_hash': 'SHA256:a'}]}
    with pytest.raises(ValueError):
        read_snapshot(io.StringIO(json.dumps(payload)))


@pytest.mark.parametrize('outcome', ['success', 'tool_error', 'exception', 'bad_json'])
def test_packet_temp_output_is_closed_on_every_exit(monkeypatch, outcome):
    from dragontools.worker.duration_packet_integrity import PacketIntegrityVerifier
    monkeypatch.setattr('dragontools.worker.duration_packet_integrity.tool_available', lambda *a: True)
    handles = []
    def run(cmd, *, stdout_file, **kwargs):
        handles.append(stdout_file)
        if outcome == 'exception':
            raise OSError('disk unavailable')
        if outcome == 'bad_json':
            stdout_file.write('{broken')
        else:
            _write_packets(stdout_file, 10)
        return SimpleNamespace(returncode=1 if outcome == 'tool_error' else 0, stdout='', stderr='')
    result = PacketIntegrityVerifier(ffprobe_path='fake', run_tool=run).validate(
        'before', 'after', reference_duration_s=1, frame_rate=None)
    assert result.ok is (outcome == 'success')
    assert handles and all(handle.closed for handle in handles)


def test_summary_dialog_releases_rows_after_close(monkeypatch):
    from dragontools.gui import run_summary_dialog as module
    from dragontools.tests.test_conversion_result_service import _service
    dialog = Mock()
    dialog.action.return_value = 'close'
    factory = Mock(return_value=dialog)
    factory.ACTION_REQUEUE_FAILED = 'retry'
    monkeypatch.setattr(module, 'RunSummaryDialog', factory)
    service, *_ = _service()
    service._build_run_summary = lambda *a, **kw: {'rows': []}
    assert service._show_run_summary_dialog(None, move_ok=0, move_errors=0) == []
    dialog.deleteLater.assert_called_once()


def test_real_ffprobe_disk_backed_packet_proof(tmp_path, monkeypatch):
    from dragontools.worker.duration_packet_integrity import PacketIntegrityVerifier
    root = Path(__file__).resolve().parents[2] / 'third_party' / 'FFmpeg'
    ffmpeg, ffprobe = root / 'ffmpeg.exe', root / 'ffprobe.exe'
    if not ffmpeg.exists() or not ffprobe.exists():
        pytest.skip('Local FFmpeg tools unavailable')
    monkeypatch.setattr('dragontools.worker.tool_process_lifecycle.mark_activity', lambda *a, **kw: None)
    path = tmp_path / 'video.mkv'
    result = run_tool([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'color=size=32x32:rate=25',
                       '-t', '0.4', '-c:v', 'ffv1', path], timeout_s=15)
    assert result.ok, result.stderr
    verifier = PacketIntegrityVerifier(ffprobe_path=str(ffprobe), run_tool=run_tool)
    result = verifier.validate(str(path), str(path), reference_duration_s=1, frame_rate=None)
    assert result.ok, result.messages
