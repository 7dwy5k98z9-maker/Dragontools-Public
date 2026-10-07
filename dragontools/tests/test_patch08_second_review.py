from pathlib import Path
from types import SimpleNamespace

import pytest

from dragontools.tests.test_review_patch_v12_dv_transaction_safety import _worker, _runner
from dragontools.worker.dv_remux_output import DVOutputManager


def test_verified_candidate_survives_unavailable_archive(tmp_path, monkeypatch):
    source = tmp_path / 'Film.mkv'
    source.write_bytes(b'original')
    worker = _worker(_log=lambda *_: None)
    manager = DVOutputManager(worker)
    staging = Path(manager.build_output_path(str(source)))
    monkeypatch.setattr(manager, 'verify_output', lambda **_: True)
    monkeypatch.setattr(manager, 'replace_output_if_needed', lambda *_: (_ for _ in ()).throw(OSError('disk locked')))
    monkeypatch.setattr(manager, 'preserve_failed_output', lambda *_a, **_k: None)
    assert _runner(worker, source, staging, manager).run(str(source)) is False
    assert staging.is_file()
    assert source.read_bytes() == b'original'


def test_sidecars_roll_back_on_unexpected_install_exception(tmp_path, monkeypatch):
    import dragontools.worker.dv_remux_job as module
    source = tmp_path / 'Film.mkv'
    source.write_bytes(b'original')
    old_sub = tmp_path / 'Film.de.srt'
    old_sub.write_text('user subtitle', encoding='utf-8')
    worker = _worker(_log=lambda *_: None)
    manager = DVOutputManager(worker)
    staging = Path(manager.build_output_path(str(source)))
    new_sub = staging.with_suffix('.de.srt')
    new_sub.write_text('generated subtitle', encoding='utf-8')
    monkeypatch.setattr(manager, 'verify_output', lambda **_: True)
    monkeypatch.setattr(manager, 'replace_output_if_needed', lambda *_: (_ for _ in ()).throw(RuntimeError('unexpected install failure')))
    journal = SimpleNamespace(set_status=lambda *_a, **_k: None, finish=lambda: None)
    monkeypatch.setattr(module.SidecarJournal, 'start', lambda **_: journal)
    runner = _runner(worker, source, staging, manager)
    monkeypatch.setattr(runner, '_export_sidecars_if_needed', lambda **_: [str(new_sub)])
    assert runner.run(str(source)) is False
    assert old_sub.read_text(encoding='utf-8') == 'user subtitle'
    assert source.read_bytes() == b'original'


def test_archive_returns_durable_path_even_if_logging_fails(tmp_path):
    def broken(*_):
        raise RuntimeError('logger closed')
    worker = _worker(log=broken)
    manager = DVOutputManager(worker)
    source = tmp_path / 'Film.mkv'
    source.write_bytes(b'original')
    candidate = Path(manager.build_output_path(str(source)))
    candidate.write_bytes(b'usable video')
    archived = manager.preserve_failed_output(str(source), str(candidate))
    assert archived and Path(archived).read_bytes() == b'usable video'


def test_successful_commit_is_not_lost_to_logging_failure(tmp_path, monkeypatch):
    import dragontools.worker.dv_remux_output as module
    from dragontools.core.output_replace import commit_staged_output
    def broken(*_):
        raise RuntimeError('logger closed')
    worker = _worker(log=broken, _log=broken)
    manager = DVOutputManager(worker)
    source = tmp_path / 'Film.mkv'
    source.write_bytes(b'original' * 256)
    candidate = Path(manager.build_output_path(str(source)))
    candidate.write_bytes(b'converted' * 256)
    monkeypatch.setattr(module, 'validate_output_size_policy', lambda **_: (True, None))
    monkeypatch.setattr(module, 'commit_staged_output', lambda **kwargs: commit_staged_output(**kwargs, journal_root=tmp_path / 'journals'))
    result = manager.replace_output_if_needed(str(source), str(candidate))
    assert result.ok and result.committed
    assert Path(result.output_path).read_bytes() == b'converted' * 256


@pytest.mark.parametrize('invalid', [True, 1.5, -1, None])
def test_remux_never_guesses_first_video_for_invalid_explicit_analysis(tmp_path, invalid):
    from dragontools.worker.dv_remux_pipeline import DVRemuxPipelineRunner
    calls = []
    output = tmp_path / 'video.hevc'
    def run(cmd, *_a, **_k):
        calls.append(cmd)
        output.write_bytes(b'wrong video')
        return 0
    worker = _worker(tools=SimpleNamespace(ffmpeg='ffmpeg'))
    pipeline = DVRemuxPipelineRunner(worker, SimpleNamespace(run_cmd=run), audio_plan_builder=lambda **_: [], audio_title_builder=lambda **_: '', audio_filter_builder=lambda _: None)
    media = SimpleNamespace(primary_video=SimpleNamespace(index=invalid), ffmpeg_stream_indices_trusted=True)
    assert pipeline.extract_video('source.mkv', str(output), 1000, media_info=media) is False
    assert not calls


def test_remux_never_uses_untrusted_stream_index(tmp_path):
    from dragontools.worker.dv_remux_pipeline import DVRemuxPipelineRunner
    calls = []
    worker = _worker(tools=SimpleNamespace(ffmpeg='ffmpeg'))
    output = tmp_path / 'video.hevc'
    def run(cmd, *_a, **_k):
        calls.append(cmd)
        output.write_bytes(b'wrong video')
        return 0
    pipeline = DVRemuxPipelineRunner(worker, SimpleNamespace(run_cmd=run), audio_plan_builder=lambda **_: [], audio_title_builder=lambda **_: '', audio_filter_builder=lambda _: None)
    media = SimpleNamespace(primary_video=SimpleNamespace(index=2), ffmpeg_stream_indices_trusted=False)
    assert pipeline.extract_video('source.mkv', str(output), 1000, media_info=media) is False
    assert not calls


def test_final_hdr10plus_presence_always_requires_content_verification():
    from dragontools.worker.dv_final_metadata_verifier import DVFinalMetadataVerifier
    from dragontools.worker.dv_runtime_models import DVTempState
    service = DVFinalMetadataVerifier(tools=SimpleNamespace(), temp_state=DVTempState(), rpu_service=None, hdr10plus_service=None, log=lambda *_: None, verbose_log=lambda *_: None, assert_nonempty_file=lambda *_: True)
    state = SimpleNamespace(request=SimpleNamespace(output_path='out.mkv', container='mkv', profile_major=8, requires_hdr10plus=True), effective_crop=None, verified_dolby_vision=False, verified_hdr10plus=False)
    inspection = SimpleNamespace(conclusive=True, dolby_vision=True, dolby_vision_profile='8.1', hdr10plus=True)
    seen = []
    assert service.verify(state, None, inspect_dynamic_hdr=lambda *_: inspection, verify_fallback=lambda *_a, **kwargs: seen.append(kwargs) or True)
    assert seen == [{'verify_dv': True, 'verify_hdr10plus': True}]


def test_request_owns_nested_override_snapshot():
    from dragontools.worker.dv_pipeline_context import DVRunRequest
    override = {'audio': {'languages': ['de']}}
    request = DVRunRequest.create(input_path='in.mkv', output_path='out.mkv', media_info=SimpleNamespace(dv_profile_major=8), vf_args=[], audio_args=[], audio_input_args=[], sn=[], crop=None, override=override, preserve_hdrplus=False, container='mkv')
    override['audio']['languages'].append('en')
    assert request.override == {'audio': {'languages': ['de']}}


@pytest.mark.parametrize('terminal_flag,expected', [('aborted', 130), ('timed_out', 124)])
def test_remux_process_preserves_terminal_flags_with_zero_exitcode(monkeypatch, terminal_flag, expected):
    import dragontools.worker.dv_remux_process as module
    from dragontools.worker.tool_runner import ToolRunResult
    result = ToolRunResult(command=['ffmpeg'], returncode=0, **{terminal_flag: True})
    monkeypatch.setattr(module, 'run_tool', lambda *_a, **_k: result)
    worker = _worker(_log=lambda *_: None)
    runner = module.DVRemuxProcessRunner(worker)
    assert runner.run_cmd(['ffmpeg', '-version']) == expected
    assert runner.run_abortable_capture(['dovi_tool', '-V'])[0] == expected


@pytest.mark.parametrize('overwrite', [False, True])
def test_output_reservation_is_unique_across_independent_workers(tmp_path, overwrite):
    source = tmp_path / 'Film.mkv'
    source.write_bytes(b'original')
    managers = [DVOutputManager(_worker(overwrite_original=overwrite)) for _ in range(2)]
    paths = [Path(manager.build_output_path(str(source))) for manager in managers]
    assert paths[0] != paths[1]
    assert all(p.is_file() for p in paths)


@pytest.mark.parametrize('overwrite', [False, True])
def test_cleanup_never_deletes_other_workers_candidate(tmp_path, overwrite):
    source = tmp_path / 'Film.mkv'
    source.write_bytes(b'original')
    manager = DVOutputManager(_worker(overwrite_original=overwrite))
    owned = Path(manager.build_output_path(str(source)))
    owned.write_bytes(b'owned')
    other = owned.with_name('Other.mp4' if overwrite else 'Film_DV_Remux_notes.mp4')
    other.write_bytes(b'other job or user file')
    manager.cleanup_incomplete(str(source), str(other))
    assert other.read_bytes() == b'other job or user file'
    assert manager.preserve_failed_output(str(source), str(other)) is None


def test_encoder_config_owns_nested_options():
    from dragontools.worker.dv_runtime_models import DVEncoderConfig
    options = {'cpu': {'extra': ['a']}}
    config = DVEncoderConfig('h265', 21, 'medium', options)
    options['cpu']['extra'].append('b')
    assert config.options == {'cpu': {'extra': ['a']}}


def test_sidecar_transaction_rolls_back_if_journal_status_callback_raises(tmp_path, monkeypatch):
    import dragontools.worker.dv_remux_job as module
    source = tmp_path / 'Film.mkv'
    source.write_bytes(b'original')
    user_sub = tmp_path / 'Film.de.srt'
    user_sub.write_text('user', encoding='utf-8')
    worker = _worker(_log=lambda *_: None)
    manager = DVOutputManager(worker)
    staging = Path(manager.build_output_path(str(source)))
    staged_sub = staging.with_suffix('.de.srt')
    staged_sub.write_text('generated', encoding='utf-8')
    monkeypatch.setattr(manager, 'verify_output', lambda **_: True)
    journal = SimpleNamespace(set_status=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError('journal status callback failed')), finish=lambda: None)
    monkeypatch.setattr(module.SidecarJournal, 'start', lambda **_: journal)
    runner = _runner(worker, source, staging, manager)
    monkeypatch.setattr(runner, '_export_sidecars_if_needed', lambda **_: [str(staged_sub)])
    assert runner.run(str(source)) is False
    assert user_sub.read_text(encoding='utf-8') == 'user'


@pytest.mark.parametrize('bad', [True, 1.5, -1])
def test_pgs_mapping_rejects_invalid_tool_specific_ids(bad):
    import json
    from dragontools.worker.dv_mkv_source_subtitles import resolve_subtitle_ids
    def capture(cmd):
        payload = {'streams': [{'index': 3}]} if '-select_streams' in cmd else {'tracks': [{'type': 'subtitles', 'id': bad}]}
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload))
    with pytest.raises(ValueError):
        resolve_subtitle_ids(path='source.mkv', ffprobe='ffprobe', mkvmerge='mkvmerge', capture=capture)


def test_pgs_inventory_accepts_semantically_valid_mkvmerge_warning():
    import json
    from dragontools.worker.dv_mkv_source_subtitles import resolve_subtitle_ids
    def capture(cmd):
        warning = '-J' in cmd
        payload = {'tracks': [{'type': 'subtitles', 'id': 9}]} if warning else {'streams': [{'index': 3}]}
        return SimpleNamespace(returncode=1 if warning else 0, stdout=json.dumps(payload))
    assert resolve_subtitle_ids(path='source.mkv', ffprobe='ffprobe', mkvmerge='mkvmerge', capture=capture) == {3: 9}


@pytest.mark.parametrize('container,remux', [('mkv', False), ('mp4', False), ('mkv', True), ('mp4', True)])
def test_missing_required_mux_track_fails_before_tool_runs(tmp_path, container, remux):
    from dragontools.worker.dv_audio_mux_service import DVMuxAudioTrack
    from dragontools.worker.dv_mkv_muxer import DVMKVMuxer
    from dragontools.worker.dv_mp4box_muxer import DVMP4BoxMuxer
    from dragontools.worker.dv_remux_muxers import DVRemuxMuxer
    output = tmp_path / ('out.' + container)
    video = tmp_path / 'video.hevc'
    video.write_bytes(b'video')
    missing = tmp_path / 'deleted_audio.mka'
    calls = []
    def run(cmd, **_):
        calls.append(cmd)
        output.write_bytes(b'video without requested audio')
        return 0
    if remux:
        runner = SimpleNamespace(run_abortable_capture=lambda cmd, **kw: (run(cmd, **kw), '', ''))
        mux = DVRemuxMuxer(_worker(container=container, tools=SimpleNamespace(mp4box='MP4Box', mkvmerge='mkvmerge')), runner)
        ok = mux.mux(str(video), [(str(missing), {})], str(output))
    else:
        mux = DVMKVMuxer(mkvmerge_path='mkvmerge', audio_track_name=lambda _: '') if container == 'mkv' else DVMP4BoxMuxer(mp4box_path='MP4Box', audio_track_name=lambda _: '')
        ok = mux.mux_final_output(run, output_path=str(output), injected_hevc=video, mux_tracks=[DVMuxAudioTrack(0, missing, {})])
    assert ok is False
    assert not calls
