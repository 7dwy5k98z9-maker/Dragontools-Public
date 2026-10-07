"""Real media assertions for audio metadata and time-domain alignment."""
import json
import subprocess
import wave
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pytest

from dragontools.tests.ci_requirements import external_media_environment
from dragontools.tests.test_review11_audio import _audio, _mapping, _rules
from dragontools.core.audio_sync_planner import AudioSyncPlanner
from dragontools.core.media_analyzer import analyze_media
from dragontools.rules.audio_plan import compute_audio_track_plan
from dragontools.worker.audio_mux_plan_service import AudioMuxPlanService
from dragontools.worker.audio_mux_output_verifier import AudioMuxOutputVerifier
from dragontools.worker.audio_mux_job import AudioMuxJobRunner

pytestmark = pytest.mark.media_integration


def run(command):
    result = subprocess.run(command, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr[-3000:]
    return result


@pytest.fixture
def tools():
    env = external_media_environment()
    if not env.ffmpeg or not env.ffprobe:
        pytest.skip('FFmpeg/ffprobe unavailable')
    return NS(ffmpeg=env.ffmpeg, ffprobe=env.ffprobe)


@pytest.mark.parametrize('channels,layout,codec,title', [
    (1,'mono','aac','Deutsch AAC Mono 128kbps'),
    (2,'stereo','aac','Deutsch AAC Stereo 256kbps'),
    (6,'5.1','eac3','Deutsch EAC3 5.1 640kbps'),
])
def test_real_audio_mux_preserves_flags_language_and_target_format(tmp_path, tools, channels, layout, codec, title):
    source=tmp_path/'Quelle ä.mkv'; output=tmp_path/'Ausgabe ü.mkv'
    run([tools.ffmpeg,'-y','-v','error','-f','lavfi','-i','testsrc2=size=128x72:rate=24000/1001:duration=1',
         '-f','lavfi','-i',f'anullsrc=r=48000:cl={layout}', '-t','1','-c:v','libx264',
         '-preset','ultrafast','-c:a','pcm_s16le','-metadata:s:a:0','language=ger',
         '-disposition:a:0','default+forced',str(source)])
    media=analyze_media(str(source), tools)
    plan=compute_audio_track_plan(media.audio_streams,None,'mkv',rules=_rules(),apply_language_rules=False)
    planner=AudioMuxPlanService(tools=tools)
    contract=planner.build_expected_contract(str(source),media,plan)
    run(planner.build_ffmpeg_cmd(str(source),str(output),plan))
    payload=json.loads(run([tools.ffprobe,'-v','error','-show_streams','-of','json',str(output)]).stdout)
    audio=next(s for s in payload['streams'] if s['codec_type']=='audio')
    assert audio['codec_name']==codec and audio['channels']==channels
    assert audio['tags']['language']=='deu' and audio['tags']['title']==title
    assert audio['disposition']['forced']==1 and audio['disposition']['default']==1
    verified=AudioMuxOutputVerifier(ffprobe_path=tools.ffprobe).verify(output_path=str(output),expected_duration_ms=1000,expected_contract=contract)
    assert verified.ok, verified.messages


@pytest.mark.parametrize('offset', [-.25,.25])
@pytest.mark.parametrize('speed', [1.0,24000/25025])
@pytest.mark.parametrize('segmented', [False,True])
def test_real_fractional_tempo_and_signed_offsets_align_audio_pulse(tmp_path, tools, offset, speed, segmented):
    source=tmp_path/'pulse.wav'; output=tmp_path/'aligned.wav'
    expression=r'if(between(t\,1\,1.2)\,0.8*sin(2*PI*440*t)\,0)'
    run([tools.ffmpeg,'-y','-v','error','-f','lavfi','-i',f'aevalsrc={expression}:s=48000:d=4', '-c:a','pcm_s16le',str(source)])
    mapping=_mapping([_audio(1)])
    mapping.source_info.duration_s=4; mapping.target_info.duration_s=4
    mapping.source_info.fps_label='25'; mapping.target_info.fps_label='24000/1001'
    mapping.target_info.frame_rate_mode='VFR'
    mapping.speed_factor=speed; mapping.offset_s=offset
    cuts=None
    if segmented:
        from dragontools.tests.test_patch11_second_review import _cut
        mapping.mode='C'
        cuts=[_cut(2,2.2,speed*2+offset,speed*2.2+offset)]
    plan=AudioSyncPlanner().build_plan(mapping,cut_results=cuts)
    assert not plan.blocked
    run([tools.ffmpeg,'-y','-v','error','-i',str(source),'-af',plan.filter_graph,'-c:a','pcm_s16le',str(output)])
    with wave.open(str(output),'rb') as handle:
        assert handle.getnframes()==192000
        samples=np.frombuffer(handle.readframes(handle.getnframes()),dtype='<i2').astype(float)
    energy=np.sqrt(np.mean(samples.reshape(-1,480)**2,axis=1))
    start=np.flatnonzero(energy>2000)[0]*.01
    assert start==pytest.approx((1-offset)/speed,abs=.045)


def test_real_audio_mux_job_publishes_verified_output_and_keeps_source(tmp_path, tools):
    from dragontools.tests.test_patch11_second_review import Signal
    source=tmp_path/'Quelle Ω.mkv'
    run([tools.ffmpeg,'-y','-v','error','-f','lavfi','-i','testsrc2=size=128x72:rate=25:duration=1',
         '-f','lavfi','-i','sine=frequency=440:duration=1','-c:v','libx264','-preset','ultrafast',
         '-c:a','aac','-metadata:s:a:0','language=deu',str(source)])
    before=source.read_bytes()
    worker=NS(tools=tools,progress_file=Signal(),log_line=Signal(),file_result=Signal(),
        overwrite_original=False,abort_requested=False,abort_type='sofort',run_ffmpeg_with_progress=lambda cmd,*a:run(cmd).returncode)
    planner=AudioMuxPlanService(tools=tools)
    AudioMuxJobRunner(worker,planner=planner,verifier=AudioMuxOutputVerifier(ffprobe_path=tools.ffprobe)).run(str(source))
    assert worker.file_result.values[-1][1] is True
    assert Path(worker.file_result.values[-1][2]).is_file()
    assert source.read_bytes()==before
    assert not list(tmp_path.glob('dragontools_audio_mux_*'))
