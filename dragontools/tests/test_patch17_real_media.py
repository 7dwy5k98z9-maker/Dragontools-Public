"""Exercise utility planning, media proof and publication with installed tools."""
from pathlib import Path
from types import SimpleNamespace
import shutil
import subprocess
import threading
import sys
import time
from unittest.mock import Mock

import pytest

from dragontools.tests.ci_requirements import external_media_environment
from dragontools.tests.test_review17_iso_merge_remux import _Signal, _Logger


@pytest.fixture
def media_tools():
    import os
    environment = external_media_environment()
    if not environment.ffmpeg or not environment.ffprobe:
        pytest.skip('FFmpeg und ffprobe fehlen')
    mkvmerge = os.environ.get('DRAGONTOOLS_MKVMERGE') or shutil.which('mkvmerge')
    return SimpleNamespace(ffmpeg=environment.ffmpeg, ffprobe=environment.ffprobe, mkvmerge=mkvmerge)


def _run(command):
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr[-3000:]
    return result.returncode


def _source(path, tools):
    _run([tools.ffmpeg, '-n', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=128x72:rate=25:duration=1',
        '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1', '-map', '1:a', '-map', '0:v',
        '-c:a', 'aac', '-c:v', 'libx264', '-preset', 'ultrafast', '-metadata:s:a:0', 'language=deu',
        '-disposition:a:0', 'default', str(path)])


@pytest.mark.media_integration
def test_real_mp4_remux_maps_actual_video_and_verifies_before_publish(tmp_path, media_tools):
    from dragontools.core.media_analyzer import analyze_media
    from dragontools.worker.mp4_remux_plan import MP4RemuxPlanner
    from dragontools.worker.mp4_remux_file_service import MP4RemuxFileService
    from dragontools.worker.mp4_remux_output_verifier import MP4RemuxOutputVerifier
    source, output = tmp_path / 'Quelle ä.mkv', tmp_path / 'Ausgabe Ω.mp4'
    _source(source, media_tools)
    original = source.read_bytes()
    media = analyze_media(str(source), media_tools)
    assert media.primary_video.index == 1
    results = []
    planner = MP4RemuxPlanner(ffmpeg_path=media_tools.ffmpeg, apply_audio_rules=False,
        export_subtitles=False, ignore_subtitles=True, subtitle_rules={}, faststart=True,
        log=lambda *a: None, log_audio=lambda *a, **kw: None)
    service = MP4RemuxFileService(planner=planner, logger=_Logger(), log=lambda *a: None,
        run_ffmpeg=lambda command, *a: _run(command), export_sidecars=Mock(), commit_sidecars=Mock(),
        cleanup_sidecars=Mock(), abort_requested=lambda: False, emit_file_result=lambda *a: results.append(a),
        emit_file_progress=lambda *a: None, export_subtitles=False, ignore_subtitles=True,
        output_verifier=MP4RemuxOutputVerifier(ffprobe_path=media_tools.ffprobe))
    assert service.remux(str(source), str(output), media, current_index=1, total_files=1, user_abort_error=RuntimeError), results
    assert source.read_bytes() == original and output.is_file()
    assert not list(tmp_path.glob('.__dragontools_mp4_remux_*'))


@pytest.mark.media_integration
def test_real_iso_fallback_uses_a_source_preservation_contract(tmp_path, media_tools):
    from dragontools.worker.iso_ffmpeg_fallback_service import ISOFFmpegFallbackService
    source, output = tmp_path / 'Lesbarer Stream Ü.mkv', tmp_path / 'Disc Ω.mkv'
    _source(source, media_tools)
    original = source.read_bytes()
    inspector = SimpleNamespace(ffmpeg_fallback_candidate=lambda _: ({'mode': 'file', 'path': source}, None),
        unique_fallback_output=lambda *a: output)
    worker = SimpleNamespace(abort_requested=False, abort_type='sofort')
    service = ISOFFmpegFallbackService(tools=media_tools, inspector=inspector, worker=worker,
        log=lambda *a: None, progress=lambda *a: None)
    result = service.extract(str(source), str(tmp_path))
    assert result.ok, result.error
    assert source.read_bytes() == original and output.is_file()
    assert not list(tmp_path.glob('.__dragontools_iso_ffmpeg_*'))


@pytest.mark.media_integration
def test_real_merge_analyzes_and_verifies_the_complete_combined_output(tmp_path, media_tools):
    if not media_tools.mkvmerge or not Path(media_tools.mkvmerge).is_file():
        pytest.skip('MKVToolNix fehlt')
    from dragontools.worker.merge_analysis import MergeAnalysisMixin
    from dragontools.worker.merge_executor import MergeExecutorMixin
    from dragontools.worker.merge_plan import MergePlanMixin
    class Host(MergeAnalysisMixin, MergeExecutorMixin, MergePlanMixin):
        tools = media_tools
        abort_requested = False
        abort_type = 'sofort'
        progress = _Signal()
        file_progress = _Signal()
        _logger = _Logger()
        def _log(self, *a):
            pass
    first, second, output = tmp_path / 'Teil ä.mkv', tmp_path / 'Teil Ω.mkv', tmp_path / 'Gesamt ü.mkv'
    _source(first, media_tools)
    shutil.copyfile(first, second)
    original = first.read_bytes()
    host = Host()
    infos = host._analyze_inputs([str(first), str(second)])
    plan = host._build_merge_plan(infos, str(output), 'lossless')
    assert plan['lossless_possible'], plan['reasons']
    assert host._run_lossless_merge(plan)
    assert first.read_bytes() == second.read_bytes() == original and output.is_file()
    assert not list(tmp_path.glob('.__dragontools_merge_*'))


def test_native_analysis_abort_stops_only_the_workers_own_process(tmp_path):
    from dragontools.worker.utility_media_analysis import analyze_owned_media
    ready = tmp_path / 'Analyse läuft Ω.txt'
    worker = SimpleNamespace(_lock=threading.Lock(), _current_process=None,
        abort_requested=False, abort_type='sofort', _paused=False)
    errors = []
    def analyzer(path, tools, *, run_process):
        return run_process([sys.executable, '-c',
            'import pathlib,sys,time;pathlib.Path(sys.argv[1]).write_text("ready");time.sleep(30)', str(ready)])
    def work():
        try:
            analyze_owned_media('source', None, worker=worker, analyzer=analyzer)
        except RuntimeError as exc:
            errors.append(exc)
    unrelated = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(30)'],
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
    thread = threading.Thread(target=work)
    owned = None
    try:
        thread.start()
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        assert ready.exists()
        with worker._lock:
            owned = worker._current_process
        assert owned is not None
        worker.abort_requested = True
        thread.join(6)
        assert not thread.is_alive() and errors
        assert owned.poll() is not None and unrelated.poll() is None
        assert worker._current_process is None
    finally:
        worker.abort_requested = True
        thread.join(7)
        if owned is not None and owned.poll() is None:
            from dragontools.core.owned_process import terminate_owned_job, close_owned_job
            terminate_owned_job(owned)
            close_owned_job(owned)
        unrelated.terminate()
        unrelated.wait(timeout=5)
