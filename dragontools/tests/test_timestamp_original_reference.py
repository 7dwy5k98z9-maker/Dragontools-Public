from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from dragontools.worker.duration_repair_models import MediaTimingInfo, TimestampRepairResult
from dragontools.worker.duration_repair_orchestrator import DurationRepairOrchestrator
from dragontools.worker.duration_repair_stream_guard import StreamInventory
from dragontools.worker.duration_timestamp_service import TimestampRepairService
from dragontools.tests.test_patch_ba_source_timing_reference import _ok_verify


def _services(tmp_path, monkeypatch, duration_s=7732.939, source_changes=None, before_changes=None):
    monkeypatch.setattr('dragontools.worker.duration_timestamp_service.tool_available', bool)
    monkeypatch.setattr('dragontools.worker.duration_timestamp_helpers.tool_available', bool)
    monkeypatch.setattr('dragontools.worker.duration_timestamp_plan.tool_available', bool)
    source = MediaTimingInfo(
        path=str(tmp_path / 'original.mkv'), container_duration_s=duration_s,
        video_duration_s=duration_s, frame_rate=Fraction(24000, 1001),
        frame_rate_mode='CFR', video_stream_count=1,
    )
    source = replace(source, **(source_changes or {}))
    before = MediaTimingInfo(
        path=str(tmp_path / 'output.mkv'), container_duration_s=4299697.569,
        video_duration_s=4299697.5, audio_duration_s=duration_s,
        chapter_end_s=duration_s, video_frame_count=103089549,
        frame_rate=Fraction(25), frame_rate_mode='CFR', video_stream_count=1,
        audio_stream_count=1,
    )
    before = replace(before, **(before_changes or {}))
    events = []

    def timing(path, **kwargs):
        if path == source.path:
            events.append('original')
            return source
        return before

    analyzer = SimpleNamespace(get_media_timing_info=timing)
    runtime = SimpleNamespace(
        ffprobe_path='ffprobe', mkvmerge_path='mkvmerge', ffmpeg_path='', mp4box_path='',
        mediainfo_path='', log=Mock(), replace_file=Mock(),
        run_tool=Mock(return_value=SimpleNamespace(
            returncode=0, stdout='{"tracks":[{"type":"video","id":7}]}', stderr='')),
    )
    service = TimestampRepairService(runtime, analyzer)
    inventory = StreamInventory('ffprobe', True, video=1, audio=1)
    service._stream_guard.inspect_all = Mock(return_value=(inventory, inventory, inventory))
    service._original_timeline_service.try_repair = Mock(return_value=TimestampRepairResult(
        reason='Original-Timeline nicht verfügbar.'))
    captured = {}

    def candidate(**kwargs):
        captured.update(kwargs)
        events.append('timestamp')
        return TimestampRepairResult(attempted=True, repaired=True,
            verify_result=_ok_verify(duration_s), duration_s=duration_s)

    service._attempt_candidate = Mock(side_effect=candidate)
    invalid = _ok_verify(before.container_duration_s)
    invalid.duration_ok = False
    invalid.messages = ['Ausgabedauer ist nicht plausibel.']
    kwargs = dict(out=Path(before.path), container='mkv', base_dir=tmp_path,
        expected_duration_ms=round(duration_s * 1000), expected_duration_s=duration_s,
        source_has_audio=True, reference_result=invalid, source_path=source.path)
    return service, kwargs, source, before, captured, events


@pytest.mark.parametrize('duration_s', [7732.939, 6 * 3600, 12 * 3600])
@pytest.mark.parametrize('frame_count,mode', [(103089549, 'CFR'), (None, 'unknown'), (103089549, 'VFR')])
def test_original_rate_allows_candidate_despite_damaged_output_metadata(tmp_path, monkeypatch, duration_s, frame_count, mode):
    service, kwargs, source, before, captured, _ = _services(tmp_path, monkeypatch, duration_s,
        before_changes={'video_frame_count': frame_count, 'frame_rate_mode': mode})
    result = service.try_repair(**kwargs)
    assert result.repaired
    command = captured['command']
    assert command[command.index('--default-duration') + 1] == '7:24000/1001fps'
    assert captured['source_reference'] is source
    assert captured['before'].frame_rate == source.frame_rate
    assert captured['before'].video_frame_count == frame_count
    assert before.frame_rate == Fraction(25)  # output diagnostics were not mutated
    assert any('Timestamp-Rekonstruktion aus Original' in line for line in captured['timing_summary'])


def test_original_rate_also_repairs_duration_error_below_extreme_threshold(tmp_path, monkeypatch):
    service, kwargs, _, _, captured, _ = _services(tmp_path, monkeypatch,
        before_changes={'container_duration_s': 9000.0, 'video_duration_s': 9000.0,
                        'video_frame_count': 225000})
    assert service.try_repair(**kwargs).repaired
    assert '--default-duration' in captured['command']


@pytest.mark.parametrize('source_changes', [
    {'frame_rate': None}, {'frame_rate_mode': 'unknown'}, {'frame_rate_mode': 'VFR'},
    {'container_duration_s': None, 'video_duration_s': None},
    {'video_stream_count': 2},
])
def test_missing_or_variable_original_rate_does_not_authorize_cfr(tmp_path, monkeypatch, source_changes):
    service, kwargs, _, _, _, _ = _services(tmp_path, monkeypatch, source_changes=source_changes)
    assert not service.try_repair(**kwargs).repaired
    service._attempt_candidate.assert_not_called()


def test_output_cannot_be_its_own_original_reference(tmp_path, monkeypatch):
    service, kwargs, _, before, _, _ = _services(tmp_path, monkeypatch,
        source_changes={'path': str(tmp_path / 'output.mkv')})
    assert Path(kwargs['source_path']) == kwargs['out']
    assert not service.try_repair(**kwargs).repaired
    service._attempt_candidate.assert_not_called()


@pytest.mark.parametrize('remux_success', [False, True])
def test_orchestrator_reads_original_only_after_failed_remux(tmp_path, monkeypatch, remux_success):
    service, kwargs, _, _, captured, events = _services(tmp_path, monkeypatch)

    def remux(**options):
        events.append('remux')
        return kwargs['reference_result'], 4299697.7, remux_success, ''

    orchestrator = DurationRepairOrchestrator(
        remux_service=SimpleNamespace(normal_remux_tool=lambda c: ('mkvmerge', 'MKVToolNix'), attempt=remux),
        timestamp_service=service, archive=SimpleNamespace(archive=Mock()), log=Mock())
    monkeypatch.setattr('dragontools.worker.duration_repair_orchestrator.tool_available', bool)
    options = {k: v for k, v in kwargs.items() if k not in {'out', 'expected_duration_s', 'reference_result'}}
    outcome = orchestrator.repair(output_path=str(kwargs['out']),
        initial_result=kwargs['reference_result'], **options)
    assert outcome.repaired
    assert events == (['remux'] if remux_success else ['remux', 'original', 'timestamp'])
    if not remux_success:
        assert '--default-duration' in captured['command']


@pytest.mark.media_integration
def test_real_mkv_timestamp_wrap_with_duration_derived_framecount(tmp_path):
    import hashlib
    import subprocess

    from dragontools.tests.ci_requirements import _resolve_tool, external_media_environment
    from dragontools.worker.duration_repair_service import DurationRepairService
    from dragontools.worker.duration_timing_analyzer import MediaTimingAnalyzer
    from dragontools.worker.output_verifier import OutputVerifier

    env = external_media_environment()
    mkvmerge = _resolve_tool('DRAGONTOOLS_MKVMERGE', 'mkvmerge.exe', 'mkvmerge')
    mediainfo = _resolve_tool('DRAGONTOOLS_MEDIAINFO', 'MediaInfo.exe', 'mediainfo')
    if not all((env.ffmpeg, env.ffprobe, mkvmerge, mediainfo)):
        pytest.skip('FFmpeg, ffprobe, MKVToolNix and MediaInfo required')

    def run(command):
        result = subprocess.run(command, capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=60)
        assert result.returncode == 0, result.stderr[-4000:]

    source = tmp_path / 'original.mkv'
    out = tmp_path / 'broken.mkv'
    run([env.ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i',
        'testsrc2=size=160x90:rate=24000/1001:duration=4', '-f', 'lavfi', '-i',
        'sine=frequency=440:sample_rate=48000:duration=4', '-c:v', 'libx264',
        '-preset', 'fast', '-bf', '0', '-c:a', 'pcm_s16le', str(source)])
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    timestamps = tmp_path / 'wrapped-timestamps.txt'
    # All video packets survive; only the last timestamp wraps by 2^32 ms.
    values = [i * 1001 / 24 for i in range(96)]
    values[-1] += 2**32
    timestamps.write_text('# timestamp format v2\n' + '\n'.join(map(str, values)) + '\n', encoding='utf-8')
    run([mkvmerge, '--disable-track-statistics-tags', '--no-track-tags', '--no-global-tags', '-o', str(out),
        '--timestamps', '0:' + str(timestamps), str(source)])

    analyzer = MediaTimingAnalyzer(ffprobe_path=env.ffprobe, mediainfo_path=mediainfo)
    source_info = analyzer.get_media_timing_info(str(source))
    broken_info = analyzer.get_media_timing_info(str(out))
    assert broken_info.video_frame_count > 1_000_000
    assert broken_info.container_duration_s > 1_000_000
    duration_ms = round(source_info.container_duration_s * 1000)
    verifier = OutputVerifier(ffprobe_path=env.ffprobe)
    initial = verifier.verify(str(out), 'mkv', expected_duration_ms=duration_ms, source_has_audio=True)
    assert not initial.duration_ok
    logs = []
    service = DurationRepairService(mkvmerge_path=mkvmerge, ffmpeg_path=env.ffmpeg,
        ffprobe_path=env.ffprobe, mediainfo_path=mediainfo, output_verifier=verifier,
        log=lambda message, level='info': logs.append(message))
    outcome = service.repair(output_path=str(out), base_dir=tmp_path, container='mkv',
        expected_duration_ms=duration_ms, source_has_audio=True,
        initial_result=initial, source_path=str(source))
    assert outcome.repaired, logs
    assert outcome.timestamp_fixed and outcome.remux_duration_s > 1_000_000
    assert '--default-duration' in outcome.timestamp_repair_cmd
    assert abs(outcome.timestamp_duration_s - source_info.container_duration_s) <= 1.0
    assert any('SHA-256' in message for message in logs)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash
