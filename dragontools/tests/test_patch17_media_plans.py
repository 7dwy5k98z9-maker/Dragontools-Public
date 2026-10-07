"""Planned stream identity and preservation metadata remain authoritative."""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest

from dragontools.core.models import MediaInfo, VideoStream
from dragontools.worker import mp4_remux_plan as module


def _planner(**kwargs):
    return module.MP4RemuxPlanner(ffmpeg_path='ffmpeg', apply_audio_rules=False,
        export_subtitles=kwargs.pop('export_subtitles', False), ignore_subtitles=False,
        subtitle_rules=kwargs.pop('subtitle_rules', {}), faststart=False,
        log=lambda *a: None, log_audio=lambda *a, **kw: None, **kwargs)


def _media():
    return MediaInfo(path='source.mkv', video_streams=[VideoStream(index=4, codec='h264',
        width=1920, height=1080, bit_depth=8)], audio_streams=[], subtitle_streams=[], duration_s=10)


def test_mp4_maps_the_selected_primary_global_stream_index(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'compute_audio_track_plan', lambda **kw: [])
    plan = _planner().build(str(tmp_path / 'source.mkv'), str(tmp_path / 'output.mp4'), _media())
    assert '0:4' in plan.command
    assert '0:v:0' not in plan.command


def test_mp4_subtitle_policy_is_computed_once_for_command_and_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'compute_audio_track_plan', lambda **kw: [])
    subtitle = SimpleNamespace(index=8, codec='subrip', language='de', title='Deutsch', default=True, forced=True)
    policy = Mock(return_value=SimpleNamespace())
    storage = Mock(side_effect=[SimpleNamespace(internal_streams=[subtitle]), SimpleNamespace(internal_streams=[])])
    monkeypatch.setattr(module, 'compute_subtitle_plan', policy)
    monkeypatch.setattr(module, 'build_mp4_subtitle_storage_plan', storage)
    plan = _planner(export_subtitles=True).build(str(tmp_path / 'source.mkv'), str(tmp_path / 'out.mp4'), _media())
    assert policy.call_count == storage.call_count == 1
    assert plan.expected_subtitle_tracks == len(plan.expected_contract.subtitle_tracks) == 1
    assert '0:8' in plan.command


def test_mp4_rules_are_a_deep_snapshot():
    rules = {'language': {'languages': ['de']}}
    planner = _planner(subtitle_rules=rules)
    rules['language']['languages'].append('en')
    assert planner.subtitle_rules['language']['languages'] == ['de']


def test_mp4_copied_audio_retains_forced_and_default_flags():
    stream = SimpleNamespace(index=1, codec='aac', channels=2, bitrate=128000, language='de', forced=True)
    decision = SimpleNamespace(stream=stream, out_idx=0, needs_transcode=False, is_extra_stereo=False,
        default=True, source_default=True, processing_notes=())
    args = _planner().build_audio_args([decision])
    flags = args[args.index('-disposition:a:0') + 1]
    assert 'forced' in flags.split('+')


def test_audio_mux_contract_requires_source_hdr_and_subtitle_metadata(monkeypatch):
    from dragontools.worker import audio_mux_plan_service as audio
    subtitle = SimpleNamespace(codec='subrip', language='de', forced=True, default=True, title='Deutsch')
    primary = SimpleNamespace(codec='hevc', bit_depth=10, width=1920, height=1080)
    media = SimpleNamespace(primary_video=primary, video_streams=[primary], subtitle_streams=[subtitle],
        is_hdr=True, has_dv=True, dv_profile_major=8, has_hdrplus=True)
    monkeypatch.setattr(audio, 'probe_output', lambda *a, **kw: SimpleNamespace(streams=[{'codec_type': 'video'}]))
    contract = audio.AudioMuxPlanService(tools=SimpleNamespace(ffprobe='ffprobe')).build_expected_contract('source.mkv', media, [])
    assert contract.require_hdr and contract.require_dolby_vision and contract.require_hdr10plus
    assert contract.expected_dolby_vision_profile == 8
    assert contract.subtitle_tracks[0].default is True
    assert contract.subtitle_tracks[0].title == 'Deutsch'


def test_audio_mux_verifier_rejects_lost_chapters():
    from dragontools.worker.audio_mux_output_verifier import AudioMuxOutputVerifier
    verifier = AudioMuxOutputVerifier(ffprobe_path='ffprobe')
    verifier._verifier = SimpleNamespace(verify=lambda *a, **kw: SimpleNamespace(
        ok=True, messages=(), chapter_count=0, audio_stream_count=0))
    assert not verifier.verify(output_path='output.mkv', expected_duration_ms=1000,
        expected_audio_tracks=0, expected_chapter_count=1).ok


def test_mp4_generic_handler_label_does_not_prove_a_requested_title():
    from dragontools.worker.output_contract_tracks import compare_audio_tracks
    from dragontools.worker.media_contract_types import ExpectedMediaContract, ExpectedAudioTrack
    contract = ExpectedMediaContract('mp4', 'h264', 1, (ExpectedAudioTrack('aac', 2, title='Deutsch'),), ())
    assert compare_audio_tracks(contract, [{'codec_name': 'aac', 'channels': 2, 'tags': {'handler_name': 'SoundHandler'}}])
    assert not compare_audio_tracks(contract, [{'codec_name': 'aac', 'channels': 2, 'tags': {'handler_name': 'Deutsch'}}])


def test_mkv_handler_cannot_replace_missing_matroska_title():
    from dragontools.worker.output_contract_tracks import compare_audio_tracks
    from dragontools.worker.media_contract_types import ExpectedMediaContract, ExpectedAudioTrack
    contract = ExpectedMediaContract('mkv', 'h264', 1, (ExpectedAudioTrack('aac', 2, title='Deutsch'),), ())
    assert compare_audio_tracks(contract, [{'codec_name': 'aac', 'channels': 2, 'tags': {'handler_name': 'Deutsch'}}])


@pytest.mark.parametrize('actual_profile', [5, 8])
def test_semantic_verification_requires_the_planned_dolby_vision_profile(tmp_path, monkeypatch, actual_profile):
    from dragontools.worker import output_verifier as verifier
    from dragontools.worker.output_probe import OutputProbeData
    from dragontools.worker.media_contract_types import ExpectedMediaContract
    output = tmp_path / 'output.mkv'
    output.write_bytes(b'DUMMY' * 512)
    stream = dict(codec_type='video', codec_name='hevc', pix_fmt='yuv420p10le', color_transfer='smpte2084',
        side_data_list=[dict(side_data_type='DOVI configuration record', dv_profile=actual_profile)])
    monkeypatch.setattr(verifier, 'probe_output', lambda *a, **kw: OutputProbeData('matroska', 1.0, (stream,)))
    contract = ExpectedMediaContract('mkv', 'hevc', 1, (), (), require_dolby_vision=True,
        expected_dolby_vision_profile=8)
    result = verifier.OutputVerifier(ffprobe_path='ffprobe').verify(str(output), 'mkv', expected_contract=contract)
    assert result.ok is (actual_profile == 8), result.messages
