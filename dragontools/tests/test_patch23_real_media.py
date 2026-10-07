"""Actual installed FFmpeg/ffprobe validate the corrected encode/mux contracts."""
import json
from pathlib import Path
import shutil
import subprocess
import threading
import array
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def tools():
    ffmpeg,ffprobe=shutil.which('ffmpeg'),shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:
        pytest.skip('FFmpeg/ffprobe für tatsächliche Medienprüfung nicht verfügbar')
    return NS(ffmpeg=ffmpeg,ffprobe=ffprobe,mediainfo=None)


def run(command):
    result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
    assert result.returncode==0,result.stderr
    return result


def media(tools,path,*,language='deu',subtitle=None,forced=False,audio_delay=0.0,timestamp_shift=0.0):
    args=[tools.ffmpeg,'-hide_banner','-loglevel','error','-y',
        '-f','lavfi','-i','testsrc2=size=96x64:rate=24000/1001:duration=3',
        '-itsoffset',str(audio_delay),'-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=3']
    if subtitle is not None: args+=['-i',str(subtitle)]
    args+=['-map','0:v:0','-map','1:a:0']
    if subtitle is not None: args+=['-map','2:s:0','-c:s','srt','-metadata:s:s:0','language=eng','-disposition:s:0','forced']
    args+=['-c:v','ffv1','-c:a','aac','-metadata:s:a:0',f'language={language}',
        '-metadata:s:a:0','title=Original Ton','-disposition:a:0','default+forced' if forced else 'default',
        '-output_ts_offset',str(timestamp_shift),str(path)]
    run(args)


def test_native_av_mux_keeps_original_forced_audio_and_subtitles(tools,tmp_path):
    from dragontools.core.audio_video_match_services import VideoAnalyzer
    from dragontools.core.audio_video_match_models import MatchPoint
    from dragontools.core.audio_video_time_mapping import classify_time_mapping
    from dragontools.worker.audio_video_match_service import AudioVideoMatchService
    from dragontools.worker.audio_video_match_contracts import AudioVideoMatchRequest,AudioVideoMatchCallbacks
    subtitle=tmp_path/'Untertitel ä.srt'; subtitle.write_text('1\n00:00:00,200 --> 00:00:02,500\nHello\n',encoding='utf-8')
    source,target,out=tmp_path/'Quelle ü.mkv',tmp_path/'Target.mkv',tmp_path/'Sync ü.mkv'
    media(tools,source); media(tools,target,language='eng',subtitle=subtitle,forced=True)
    source_info,target_info=VideoAnalyzer(tools).analyze(str(source)),VideoAnalyzer(tools).analyze(str(target))
    mapping=classify_time_mapping([MatchPoint(t,t,.99,99) for t in (.5,1,2,2.7)],source_info=source_info,target_info=target_info)
    results=[]; cb=AudioVideoMatchCallbacks(log_line=lambda m:None,progress=lambda v:None,
        analysis_ready=lambda v:None,cuts_ready=lambda v:None,plan_ready=lambda v:None,result_ready=results.append)
    worker=NS(abort_requested=False,abort_type=None,_process_lock=threading.Lock(),current_process=None)
    AudioVideoMatchService(tools=tools,callbacks=cb,process_worker=worker).execute(AudioVideoMatchRequest.create(
        'create',source_path=str(source),target_path=str(target),output_path=str(out),mapping_result=mapping))
    assert results==[str(out.resolve())] and out.is_file()
    payload=json.loads(run([tools.ffprobe,'-v','error','-show_streams','-of','json',str(out)]).stdout)
    audio=[s for s in payload['streams'] if s['codec_type']=='audio']
    text=[s for s in payload['streams'] if s['codec_type']=='subtitle']
    assert len(audio)==2 and audio[0]['tags']['language']=='deu'
    assert audio[0]['disposition']['default']==1
    assert audio[1]['disposition']['default']==0 and audio[1]['disposition']['forced']==1
    assert text[0]['disposition']['forced']==1 and text[0]['tags']['language']=='eng'
    assert not list(tmp_path.glob('.__dragontools_avmatch_*'))


def test_native_quality_encode_is_verified_then_preserved_on_second_run(tools,tmp_path):
    from dragontools.worker.quality_test_service import QualityTestService
    from dragontools.worker.quality_process_runner import QualityProcessRunner
    from dragontools.worker.quality_metrics_service import QualityMetricsService
    from dragontools.core.quality_tester import QualityTestRun
    source=tmp_path/'Quelle.mkv'; media(tools,source)
    worker=NS(abort_requested=False,abort_type=None,_abort=False,_process_lock=threading.Lock(),current_process=None)
    runner=QualityProcessRunner(worker=worker,log=lambda m:None,prefix='Native Prüfung')
    metrics=QualityMetricsService(ffmpeg=tools.ffmpeg,process_runner=runner)
    emitted=[]
    service=QualityTestService(tools=tools,process_runner=runner,metrics=metrics,log=lambda m:None,
        progress=lambda v:None,result_ready=emitted.append,is_aborted=lambda:False)
    kwargs=dict(files=[str(source)],output_dir=str(tmp_path/'Outputs'),runs=[QualityTestRun('CPU',codec='h264',preset='fast')],
        sample_count=1,sample_duration_s=1,manual_ranges='0+1')
    service.run(**kwargs)
    assert len(emitted)==1 and emitted[0].codec=='h264' and emitted[0].ssim is not None
    output=Path(emitted[0].output_path); original=output.read_bytes()
    service.run(**kwargs)
    assert service.had_failures and len(emitted)==1 and output.read_bytes()==original
    assert not list(output.parent.glob('.__dragontools_quality_*'))


@pytest.mark.parametrize('timestamp_shift',[0.0,2.0])
def test_native_matcher_preserves_audio_delay_relative_to_video(tools,tmp_path,timestamp_shift):
    from dragontools.core.audio_video_match_services import VideoAnalyzer
    from dragontools.core.audio_video_match_models import MatchPoint
    from dragontools.core.audio_video_time_mapping import classify_time_mapping
    from dragontools.worker.audio_video_match_service import AudioVideoMatchService
    from dragontools.worker.audio_video_match_contracts import AudioVideoMatchRequest,AudioVideoMatchCallbacks
    source,target,output=tmp_path/'Quelle.mkv',tmp_path/'Ziel.mkv',tmp_path/'Sync.mkv'
    media(tools,source,audio_delay=.2,timestamp_shift=timestamp_shift); media(tools,target)
    source_info,target_info=VideoAnalyzer(tools).analyze(str(source)),VideoAnalyzer(tools).analyze(str(target))
    mapping=classify_time_mapping([MatchPoint(t,t,.99,99) for t in (.5,1,2,2.7)],source_info=source_info,target_info=target_info)
    cb=lambda v:None
    service=AudioVideoMatchService(tools=tools,callbacks=AudioVideoMatchCallbacks(cb,cb,cb,cb,cb,cb))
    service.execute(AudioVideoMatchRequest.create('create',source_path=str(source),target_path=str(target),output_path=str(output),mapping_result=mapping))
    decoded=subprocess.run([tools.ffmpeg,'-v','error','-i',str(output),'-map','0:a:0',
        '-af','aresample=async=1:first_pts=0','-t','0.15','-ar','48000','-ac','1','-f','f32le','pipe:1'],
        capture_output=True,timeout=15)
    assert decoded.returncode==0,decoded.stderr
    samples=array.array('f'); samples.frombytes(decoded.stdout)
    assert samples and max(map(abs,samples))<.002


def test_native_source_visual_finishes_current_probe_after_soft_stop(tools,tmp_path):
    from dragontools.worker.source_visual_sampling import SourceVisualSampler
    from dragontools.worker.source_visual_models import SourceVisualCheckSettings
    source=tmp_path/'Quelle.mkv'; media(tools,source)
    worker=NS(abort_requested=True,abort_type='nachDatei',_process_lock=threading.Lock(),current_process=None)
    sampler=SourceVisualSampler(ffmpeg_path=tools.ffmpeg,ffprobe_path=tools.ffprobe,
        worker=worker,abort_on_request=False)
    cfg=SourceVisualCheckSettings(enabled=True,sample_duration_s=1,fps=1)
    assert not sampler.abort_requested
    assert len(sampler.read_single(source,0,cfg))>=cfg.analysis_width*cfg.analysis_height*3
    worker.abort_type='sofort'
    assert sampler.abort_requested
    assert sampler.read_single(source,0,cfg)==b''
