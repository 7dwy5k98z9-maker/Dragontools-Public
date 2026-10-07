"""Independent boundary regressions, including native mux/read-back checks."""
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from dragontools.core.models import AudioStream, MediaInfo, VideoStream
from dragontools.worker.audio_metadata_args import audio_metadata_args
from dragontools.worker.dv_audio_mux_service import DVAudioMuxService, DVMuxAudioTrack
from dragontools.worker.dv_mp4box_muxer import DVMP4BoxMuxer
from dragontools.worker.dv_mkv_muxer import DVMKVMuxer
from dragontools.worker.media_contract import build_expected_media_contract
from dragontools.worker.output_contract_tracks import compare_audio_tracks
from dragontools.worker.workflow_models import PipelineExecutionRequest
from dragontools.tests.test_workflow_pipeline_contract import _request
from dragontools.rules.audio_plan import AudioTrackDecision


@pytest.mark.parametrize('ingress', ['constructor', 'context'])
def test_pipeline_request_owns_nested_input_maps(ingress):
    override = {'audio_tracks': [{'index': 7, 'processing': {'filters': ['loudnorm']}}]}
    options = {'crop': {'regions': [1, 2]}, 'capabilities': {'av1': True}}
    if ingress == 'constructor':
        request = replace(_request(), override=override, encoder_options=options)
    else:
        context = SimpleNamespace(output_path='out.mp4', input_path='in.mkv', pipeline='dv',
            container='mp4', analysis=object(), effective_crf=20, effective_encoder_options=options)
        request = PipelineExecutionRequest.from_context(context, override)
    override['audio_tracks'][0]['processing']['filters'].append('volume=0')
    options['crop']['regions'][0] = 999
    assert request.override['audio_tracks'][0]['processing']['filters'] == ['loudnorm']
    assert request.encoder_options['crop']['regions'] == [1, 2]
    request.override['audio_tracks'][0]['index'] = 3
    assert override['audio_tracks'][0]['index'] == 7


def _decision():
    stream = AudioStream(1, 'deu', True, 'Original', 'aac', 2, bitrate=128000, default=True)
    return AudioTrackDecision(0, stream, False, 'aac', 2, 128000)


def _contract(decision, container='mkv'):
    media = MediaInfo('source.mkv', [decision.stream], [], [VideoStream(0, 'h264', 64, 64)])
    override = {'audio_mode': 'custom', 'audio_tracks': [{'index': 1, 'action': 'copy'}]}
    return build_expected_media_contract(media_info=media, file_override=override,
        container=container, pipeline='standard', strip_only=False, effective_codec='h264',
        effective_preserve_hdrplus=False, subtitle_rules={})


@pytest.mark.parametrize('lost', ['forced', 'title'])
def test_generated_contract_rejects_lost_main_audio_metadata(lost):
    contract = _contract(_decision())
    actual = {'codec_name': 'aac', 'channels': 2, 'tags': {'language': 'deu',
        'title': 'Deutsch AAC Stereo 128kbps'}, 'disposition': {'default': 1, 'forced': 1}}
    if lost == 'forced':
        actual['disposition']['forced'] = 0
    else:
        actual['tags']['title'] = 'SoundHandler'
    errors = compare_audio_tracks(contract, [actual])
    assert any(('Forced' if lost == 'forced' else 'Titel') in e for e in errors), errors


def test_dv_audio_metadata_carries_forced_primary_not_extra_stereo(monkeypatch):
    decision = _decision()
    stereo = replace(decision, out_idx=1, is_extra_stereo=True, needs_transcode=True)
    import dragontools.rules.audio_plan as module
    monkeypatch.setattr(module, 'compute_audio_track_plan', lambda **kw: [decision, stereo])
    service = DVAudioMuxService(ffmpeg_path='ffmpeg', ffprobe_path='ffprobe', mp4box_muxer=None, log=lambda *a: None)
    metadata = service.build_audio_meta(SimpleNamespace(audio_streams=[decision.stream]), {}, 'mkv')
    assert [m.get('forced') for m in metadata] == [True, False]
    assert [m['default'] for m in metadata] == [True, False]


def test_dv_remux_jobs_preserve_forced_primary_not_extra_stereo():
    from dragontools.worker.dv_remux_audio import build_dv_audio_jobs
    decision = _decision()
    stereo = replace(decision, out_idx=1, is_extra_stereo=True, needs_transcode=True)
    jobs = build_dv_audio_jobs(SimpleNamespace(container='mkv', log=lambda *a: None),
        SimpleNamespace(audio_streams=[decision.stream]), {},
        plan_builder=lambda **kw: [decision, stereo], title_builder=lambda **kw: 'Deutsch AAC',
        filter_builder=lambda d: None)
    assert [job.get('forced') for job in jobs] == [True, False]


def _tool(name, variable):
    return os.environ.get(variable) or shutil.which(name)


def _run(command, **kwargs):
    completed = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
        text=True, encoding='utf-8', errors='replace', timeout=60)
    assert completed.returncode == 0, completed.stderr
    return completed.returncode


@pytest.fixture(scope='module')
def native_audio(tmp_path_factory):
    ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:
        pytest.skip('Native audio read-back requires FFmpeg/ffprobe')
    root = tmp_path_factory.mktemp('Ton Ü Test')
    audio = root / 'Tonspur ä.m4a'
    _run([ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i',
        'sine=frequency=750:sample_rate=48000:duration=0.4', '-ac', '2', '-c:a', 'aac', str(audio)])
    video = root / 'Bild h264.h264'
    _run([ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=s=64x64:r=25:d=0.4',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '1', '-an', str(video)])
    return root, audio, video, ffmpeg, ffprobe


def _probe(ffprobe, output):
    result = subprocess.run([ffprobe, '-v', 'error', '-show_streams', '-of', 'json', str(output)],
        capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert result.returncode == 0, result.stderr
    return [s for s in json.loads(result.stdout)['streams'] if s['codec_type'] == 'audio']


@pytest.mark.media_integration
@pytest.mark.parametrize('default', [False, True])
def test_native_mp4box_honors_audio_default(native_audio, default):
    root, audio, video, ffmpeg, ffprobe = native_audio
    mp4box = _tool('MP4Box', 'DRAGONTOOLS_MP4BOX')
    if not mp4box:
        pytest.skip('MP4Box unavailable')
    muxer = DVMP4BoxMuxer(mp4box_path=mp4box, audio_track_name=lambda m: 'Deutsch AAC')
    output = root / f'Audio default {default}.mp4'
    assert muxer.mux_plain_mp4_without_dv(_run, plain_mp4=output, enc_hevc=video,
        mux_tracks=[DVMuxAudioTrack(0, audio, {'lang': 'deu', 'default': default})])
    actual = _probe(ffprobe, output)[0]
    assert bool(actual['disposition']['default']) is default
    assert actual['tags']['handler_name'] == 'Deutsch AAC'


@pytest.mark.media_integration
def test_native_dv_mkv_preserves_forced_audio(native_audio):
    root, audio, video, ffmpeg, ffprobe = native_audio
    mkvmerge = _tool('mkvmerge', 'DRAGONTOOLS_MKVMERGE')
    if not mkvmerge:
        pytest.skip('mkvmerge unavailable')
    muxer = DVMKVMuxer(mkvmerge_path=mkvmerge, audio_track_name=lambda m: 'Deutsch AAC')
    output = root / 'Audio forced.mkv'
    assert muxer.mux_final_output(_run, output_path=str(output), injected_hevc=video,
        mux_tracks=[DVMuxAudioTrack(0, audio, {'lang': 'deu', 'default': True, 'forced': True})])
    actual = _probe(ffprobe, output)[0]
    assert actual['disposition']['forced'] == 1


@pytest.mark.media_integration
def test_native_dv_remux_mkv_preserves_forced_audio(native_audio):
    from dragontools.worker.dv_remux_muxers import DVRemuxMuxer
    root, audio, video, ffmpeg, ffprobe = native_audio
    mkvmerge = _tool('mkvmerge', 'DRAGONTOOLS_MKVMERGE')
    if not mkvmerge: pytest.skip('mkvmerge unavailable')
    class Runner:
        def run_abortable_capture(self, command, **kwargs):
            result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=60)
            return result.returncode, result.stdout, result.stderr
    worker = SimpleNamespace(tools=SimpleNamespace(mkvmerge=mkvmerge), log=lambda *a: None)
    output = root/'Remux forced.mkv'
    assert DVRemuxMuxer(worker, Runner()).mux_mkv(str(video),
        [(str(audio), {'language':'deu','title':'Deutsch AAC','default':False,'forced':True})], str(output))
    actual = _probe(ffprobe, output)[0]
    assert actual['disposition']['forced']==1
    assert actual['disposition']['default']==0


@pytest.mark.media_integration
@pytest.mark.parametrize('container', ['mkv', 'mp4'])
def test_native_standard_audio_retains_requested_title(native_audio, container):
    root, audio, video, ffmpeg, ffprobe = native_audio
    decision = _decision()
    output = root / f'Standard title.{container}'
    _run([ffmpeg, '-v', 'error', '-y', '-i', str(audio), '-map', '0:a:0', '-c:a', 'copy',
        *audio_metadata_args(decision), str(output)])
    actual = _probe(ffprobe, output)[0]
    errors = compare_audio_tracks(_contract(decision, container), [actual])
    assert not errors, errors
    from dragontools.worker.audio_metadata_args import audio_output_title
    assert (actual['tags'].get('title') or actual['tags'].get('handler_name')) == audio_output_title(decision)


@pytest.mark.media_integration
@pytest.mark.parametrize('forced', [False, True])
def test_native_mp4box_subtitle_label_has_no_shell_quotes(native_audio, forced):
    root, audio, video, ffmpeg, ffprobe = native_audio
    mp4box = _tool('MP4Box', 'DRAGONTOOLS_MP4BOX')
    if not mp4box:
        pytest.skip('MP4Box unavailable')
    subtitle = root / f'Text Ü {forced}.srt'
    subtitle.write_text('1\n00:00:00,000 --> 00:00:00,350\nHallo\n', encoding='utf-8')
    output = root / f'Text {forced}.mp4'
    command = [mp4box, '-new', str(output), '-add', str(video)]
    DVMP4BoxMuxer.add_subtitle_tracks(command, [SimpleNamespace(path=subtitle,
        language='deu', title='Deutsch Untertitel', forced=forced, default=False)])
    _run(command)
    result = subprocess.run([ffprobe, '-v','error','-show_streams','-of','json',str(output)],
        capture_output=True,text=True,encoding='utf-8',timeout=30)
    actual = next(s for s in json.loads(result.stdout)['streams'] if s['codec_type']=='subtitle')
    assert actual['tags']['handler_name']=='Deutsch Untertitel'+(' [Forced]' if forced else '')
    assert bool(actual['disposition']['forced']) is forced
    assert actual['disposition']['default']==0


@pytest.mark.media_integration
def test_native_mp4box_forced_role_targets_correct_track_after_multiple_audio(native_audio):
    root, audio, video, ffmpeg, ffprobe = native_audio
    mp4box = _tool('MP4Box', 'DRAGONTOOLS_MP4BOX')
    if not mp4box: pytest.skip('MP4Box unavailable')
    subtitle = root/'Two subtitles.srt'
    subtitle.write_text('1\n00:00:00,000 --> 00:00:00,350\nHallo\n', encoding='utf-8')
    output = root/'Multiple tracks.mp4'
    command = [mp4box,'-new',str(output),'-add',str(video),'-add',str(audio),'-add',str(audio)]
    DVMP4BoxMuxer.add_subtitle_tracks(command, [SimpleNamespace(path=subtitle, language='deu',
        title=f'Text {forced}',forced=forced,default=False) for forced in [False,True]])
    _run(command)
    result = subprocess.run([ffprobe,'-v','error','-show_streams','-of','json',str(output)],
        capture_output=True,text=True,encoding='utf-8',timeout=30)
    assert result.returncode==0, result.stderr
    streams = json.loads(result.stdout)['streams']
    subtitles = [s for s in streams if s['codec_type']=='subtitle']
    assert [s['disposition']['forced'] for s in subtitles]==[0,1]
    assert all(s['disposition']['forced']==0 for s in streams if s['codec_type']!='subtitle')
    assert [s['tags']['handler_name'] for s in subtitles]==['Text False','Text True [Forced]']
