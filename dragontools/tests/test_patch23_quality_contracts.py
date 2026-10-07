from copy import deepcopy
import math
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from dragontools.core.audio_video_match_models import MatchPoint, VideoInfo
from dragontools.core.audio_video_time_mapping import classify_time_mapping
from dragontools.core.models import AudioStream
from dragontools.core.quality_tester import QualityTestRun, QualitySegment


def mapping(tmp_path):
    source, target = tmp_path/'source.mkv', tmp_path/'target.mkv'
    source.write_bytes(b'source'); target.write_bytes(b'target')
    video = lambda p: VideoInfo(str(p.resolve()), 60, audio_streams=[AudioStream(1,'de',False,'DE','aac',2)])
    return classify_time_mapping([MatchPoint(t,t,.99,99) for t in (5,20,40,55)],
        source_info=video(source),target_info=video(target))


def quality_service(**kwargs):
    from dragontools.worker.quality_test_service import QualityTestService
    values=dict(tools=NS(ffmpeg='ffmpeg',ffprobe='ffprobe'),process_runner=NS(run=lambda *a,**k:(0,'','')),
        metrics=NS(measure_encoded=lambda **k:99),log=lambda *a:None,progress=lambda *a:None,
        result_ready=lambda *a:None,is_aborted=lambda:False)
    values.update(kwargs)
    return QualityTestService(**values)


def test_quality_widget_opens_and_collects_both_default_runs(qtbot):
    from dragontools.gui.quality_tester_widget import QualityTesterWidget
    widget=QualityTesterWidget(); qtbot.addWidget(widget)
    runs=widget._collect_runs()
    assert [r['encoder'] for r in runs]==['cpu','nvenc']
    assert all(r['quality']=='23' for r in runs)


def test_matcher_path_change_revokes_analysis(qtbot,tmp_path):
    from dragontools.gui.audio_video_matcher_widget import AudioVideoMatcherWidget
    widget=AudioVideoMatcherWidget(); qtbot.addWidget(widget)
    value=mapping(tmp_path)
    widget.source_edit.setText(value.source_info.path); widget.target_edit.setText(value.target_info.path)
    widget._analysis_ready(value)
    assert widget._analysis is value
    widget.target_edit.setText(str(tmp_path/'other.mkv'))
    assert widget._analysis is None
    assert not widget.create_btn.isEnabled()


def test_matcher_result_does_not_release_running_worker(qtbot,tmp_path):
    from dragontools.gui.audio_video_matcher_widget import AudioVideoMatcherWidget
    widget=AudioVideoMatcherWidget(); qtbot.addWidget(widget)
    worker=NS(); widget._worker=worker; widget._set_running(True)
    widget._analysis_ready(mapping(tmp_path))
    assert not widget.analyze_btn.isEnabled()
    assert widget._worker is worker


def test_matcher_refine_edits_revoke_old_cut_results(qtbot,tmp_path):
    from dragontools.gui.audio_video_matcher_widget import AudioVideoMatcherWidget
    widget=AudioVideoMatcherWidget(); qtbot.addWidget(widget)
    widget._analysis=mapping(tmp_path); widget._analysis.mode='C'
    widget._cut_results=[NS(resolved=True)]
    widget.cut_ranges.setText('20-25')
    assert widget._cut_results==[]
    assert not widget.create_btn.isEnabled()


def test_match_request_owns_nested_analysis(tmp_path):
    from dragontools.worker.audio_video_match_contracts import AudioVideoMatchRequest
    value=mapping(tmp_path)
    request=AudioVideoMatchRequest.create('create',source_path=value.source_info.path,
        target_path=value.target_info.path,mapping_result=value)
    value.match_points[0].matched_time_s=999
    value.source_info.audio_streams[0].channels=8
    assert request.mapping_result.match_points[0].matched_time_s==5
    assert request.mapping_result.source_info.audio_streams[0].channels==2


def callbacks(events=None):
    from dragontools.worker.audio_video_match_contracts import AudioVideoMatchCallbacks
    events=events if events is not None else []
    return AudioVideoMatchCallbacks(log_line=lambda v:None,progress=lambda v:None,
        analysis_ready=events.append,cuts_ready=events.append,plan_ready=events.append,result_ready=events.append)


def create_service():
    from dragontools.worker.audio_video_match_create_service import AudioVideoMatchCreateService
    from dragontools.worker.audio_video_match_runtime import AudioVideoMatchToolIO,AudioVideoMatchProgress
    cb=callbacks()
    return AudioVideoMatchCreateService(tools=NS(),callbacks=cb,
        tool_io=AudioVideoMatchToolIO(callbacks=cb),progress=AudioVideoMatchProgress(cb))


def test_matcher_request_rejects_analysis_of_other_inputs(tmp_path,monkeypatch):
    from dragontools.worker.audio_video_match_contracts import AudioVideoMatchRequest
    value=mapping(tmp_path)
    other=tmp_path/'other.mkv'; other.write_bytes(b'other')
    service=create_service(); rendered=[]
    monkeypatch.setattr(service,'_render_audio',lambda *a:rendered.append(True))
    monkeypatch.setattr(service,'_mux_output',lambda *a:None)
    monkeypatch.setattr(service,'_validate_and_commit',lambda *a,**k:None)
    request=AudioVideoMatchRequest.create('create',source_path=str(other),target_path=value.target_info.path,
        mapping_result=value,output_path=str(tmp_path/'result.mkv'))
    with pytest.raises(RuntimeError,match='Analyse|Quelle|Datei'):
        service.create(request)
    assert not rendered


def test_av_commit_preserves_late_destination_and_staged_output(tmp_path,monkeypatch):
    from dragontools.worker import audio_video_match_create_service as module
    stage=tmp_path/'stage.mkv'; stage.write_bytes(b'verified')
    out=tmp_path/'out.mkv'
    def validate(*a,**k):
        out.write_bytes(b'foreign')
        return 60
    monkeypatch.setattr(module,'validate_output',validate)
    with pytest.raises((OSError,RuntimeError)):
        create_service()._validate_and_commit(NS(target_info=NS(duration_s=60)),stage,out)
    assert out.read_bytes()==b'foreign'
    assert stage.read_bytes()==b'verified'


def test_quality_case_preserves_existing_output(tmp_path,monkeypatch):
    from dragontools.core.quality_tester import quality_output_name
    run=QualityTestRun('CPU'); segment=QualitySegment(0,10,'01')
    out=tmp_path/quality_output_name('input.mkv',run,segment); out.write_bytes(b'old-good-result')
    service=quality_service(); encoded=[]
    def encode(*a):
        encoded.append(True)
        Path(a[1]).write_bytes(b'partial')
        raise RuntimeError('failed')
    monkeypatch.setattr(service,'encode_segment',encode)
    service._run_case('input.mkv',tmp_path,run,segment)
    assert out.read_bytes()==b'old-good-result'
    assert not encoded


def test_failed_quality_cases_mark_thread_error(tmp_path,monkeypatch,qapp):
    from dragontools.worker.quality_test_thread import QualityTestThread
    from dragontools.worker import quality_test_service as module
    source=tmp_path/'input.mkv'; source.write_bytes(b'input')
    monkeypatch.setattr(module,'analyze_media',lambda *a,**k:NS(duration_s=30))
    worker=QualityTestThread([str(source)],str(tmp_path/'out'),[{'name':'CPU'}],sample_count=1)
    monkeypatch.setattr(worker._service,'encode_segment',lambda *a:(_ for _ in ()).throw(RuntimeError('encode failed')))
    worker.run()
    assert worker.outcome=='error'


@pytest.mark.parametrize('defect',['nan_duration','wrong_codec','cover_art','second_video','audio'])
def test_quality_result_rejects_wrong_media_contract(tmp_path,monkeypatch,defect):
    service=quality_service(); out=tmp_path/'out.mkv'; out.write_bytes(b'encoded')
    video={'codec_type':'video','codec_name':'hevc','width':1920,'height':1080,'pix_fmt':'yuv420p10le'}
    probe={'streams':[video],'format':{'duration':'10'}}
    if defect=='nan_duration': probe['format']['duration']='NaN'
    if defect=='wrong_codec': video['codec_name']='h264'
    if defect=='cover_art': video['disposition']={'attached_pic':1}
    if defect=='second_video': probe['streams'].append(deepcopy(video))
    if defect=='audio': probe['streams'].append({'codec_type':'audio','codec_name':'aac'})
    monkeypatch.setattr(service,'probe_output',lambda p:probe)
    with pytest.raises(RuntimeError):
        service.analyze_result('input',str(out),QualityTestRun('CPU'),QualitySegment(0,10,'01'))


@pytest.mark.parametrize('score',[float('nan'),float('inf'),-1,101])
def test_quality_search_never_accepts_invalid_measurement(score):
    from dragontools.core.quality_target import adaptive_quality_search
    selected,_evaluations,met=adaptive_quality_search(min_quality=18,max_quality=30,target_vmaf=95,evaluate=lambda q:score)
    assert selected is None and not met


@pytest.mark.parametrize('metric,text',[('ssim','All:1.5'),('libvmaf','VMAF score: 101')])
def test_metrics_reject_out_of_range_scores(metric,text):
    from dragontools.worker.quality_metrics_service import QualityMetricsService
    service=QualityMetricsService(ffmpeg='ffmpeg',process_runner=NS(run=lambda *a,**k:(0,'',text)))
    notes=[]
    value=service.measure_comparison(metric=metric,file_a='a',file_b='b',start_a=0,start_b=0,
        duration=1,width=64,height=36,label=metric,notes=notes)
    assert value is None and notes


def test_quality_config_false_text_is_disabled():
    from dragontools.core.quality_target import QualityTargetConfig
    assert not QualityTargetConfig.from_encoder_options({'quality_target_enabled':'false'}).enabled


@pytest.mark.parametrize('duration',[.05,.5,1.0])
def test_quality_segments_never_run_past_short_source(duration):
    from dragontools.core.quality_tester import automatic_quality_segments,parse_quality_segments
    for segments in [automatic_quality_segments(duration_s=duration,count=3,segment_duration_s=10),
            parse_quality_segments('100%+10',duration_s=duration,default_duration_s=10)]:
        assert segments and all(0<=s.start_s<s.start_s+s.duration_s<=duration for s in segments)


def test_fractional_frame_windows_keep_budget_and_global_sampling_grid(monkeypatch):
    from dragontools.core import audio_video_frame_analysis as module
    from dragontools.core.audio_video_match_models import AudioVideoMatcherSettings
    monkeypatch.setattr(module,'FRAME_WINDOW_BYTE_BUDGET',64)
    monkeypatch.setattr(module,'_signature_from_gray_frame',lambda frame,w,h,t:NS(time_s=t))
    calls=[]
    def run(command,timeout):
        duration=float(command[command.index('-t')+1])
        fps=float(command[command.index('-vf')+1].split(',')[0].split('=')[1])
        count=min(math.ceil(duration*fps-1e-8),int(command[command.index('-frames:v')+1]) if '-frames:v' in command else 999)
        assert count<=4
        calls.append(float(command[command.index('-ss')+1]))
        return b'x'*(count*16)
    extractor=module.FrameExtractor('ffmpeg',settings=AudioVideoMatcherSettings(analysis_width=4,analysis_height=4),run_bytes=run)
    values=extractor.extract_window_signatures('in',3,4,fps=2.4)
    assert len(values)==10
    assert [v.time_s for v in values]==pytest.approx([3+i/2.4 for i in range(10)])
    assert calls==pytest.approx([3,3+4/2.4,3+8/2.4],abs=1e-8)


def test_cut_ranges_reject_collapsed_out_of_bounds_and_invalid_text():
    from dragontools.core.audio_video_match_utils import parse_cut_regions
    for value in ['70-80','bad-20','NaN-20','20-Inf']:
        with pytest.raises(ValueError): parse_cut_regions(value,duration_s=60)


def test_source_visual_short_clip_does_not_count_same_window_as_independent_hits(tmp_path,monkeypatch):
    from dragontools.worker.source_visual_check import SourceVisualCheckService,SourceVisualCheckSettings
    video=tmp_path/'short.mkv'; video.write_bytes(b'video')
    service=SourceVisualCheckService(ffmpeg_path='ffmpeg',ffprobe_path='ffprobe')
    monkeypatch.setattr(service,'_probe_duration',lambda p:1)
    monkeypatch.setattr(service,'_read_probe_frames',lambda p,t,c:bytes((0,0,0))*(c.analysis_width*c.analysis_height))
    result=service.check(video,SourceVisualCheckSettings(enabled=True,interval_percent=10,sample_duration_s=2,min_hits=4))
    assert len(result.probes)==1
    assert not result.blocked


@pytest.mark.parametrize('defect',['no_video','no_audio','cover_art','nan_duration'])
def test_av_output_cannot_pass_with_only_duration(tmp_path,monkeypatch,defect):
    from dragontools.worker import audio_video_match_render as module
    from dragontools.worker.output_probe import OutputProbeData
    out=tmp_path/'result.mkv'; out.write_bytes(b'container')
    video={'codec_type':'video','codec_name':'hevc','width':64,'height':36}
    audio={'codec_type':'audio','codec_name':'aac','channels':2}
    streams=[video,audio]; duration=60
    if defect=='no_video': streams=[audio]
    if defect=='no_audio': streams=[video]
    if defect=='cover_art': video['disposition']={'attached_pic':1}
    if defect=='nan_duration': duration=float('nan')
    monkeypatch.setattr(module,'analyze_media',lambda *a,**k:NS())
    monkeypatch.setattr(module,'probe_output',lambda *a,**k:OutputProbeData('matroska,webm',duration,tuple(streams)))
    with pytest.raises(RuntimeError): module.validate_output(out,NS(ffprobe='ffprobe'),target_duration_s=60)


def test_compare_thread_invalid_inputs_cannot_report_success(tmp_path,qapp):
    from dragontools.worker.quality_compare_thread import QualityCompareThread
    worker=QualityCompareThread(str(tmp_path/'missing-a.mkv'),str(tmp_path/'missing-b.mkv'))
    worker.run()
    assert worker.outcome=='error'


@pytest.mark.parametrize('owner',['matcher','quality_test','quality_compare'])
def test_source_analysis_participates_in_existing_worker_ownership(tmp_path,monkeypatch,owner):
    worker=NS(abort_requested=False,abort_type=None)
    value=mapping(tmp_path); observed=[]
    def analyzer(path,tools,*,run_process=None):
        assert callable(run_process)
        observed.append(path)
        run_process(['ffprobe',path])
        return NS(primary_video=NS(width=64,height=36,codec='h264'),duration_s=60,audio_streams=[AudioStream(1,'de',False,'DE','aac',2)])
    from dragontools.worker import owned_probe
    monkeypatch.setattr(owned_probe,'run_tool',lambda cmd,**k:observed.append(k['worker']) or NS(returncode=0,stdout='',stderr='',aborted=False,timed_out=False))
    if owner=='matcher':
        from dragontools.core import audio_video_match_services as core
        from dragontools.worker.audio_video_match_analysis_service import AudioVideoMatchAnalysisService
        from dragontools.worker.audio_video_match_runtime import AudioVideoMatchProgress,AudioVideoMatchToolIO
        monkeypatch.setattr(core,'analyze_media',analyzer)
        cb=callbacks(); service=AudioVideoMatchAnalysisService(tools=NS(ffmpeg='ffmpeg'),callbacks=cb,
            progress=AudioVideoMatchProgress(cb),tool_io=AudioVideoMatchToolIO(callbacks=cb,process_worker=worker))
        service._matcher().video_analyzer.analyze(value.source_info.path)
    elif owner=='quality_test':
        from dragontools.worker import quality_test_service as module
        monkeypatch.setattr(module,'analyze_media',analyzer)
        service=quality_service(process_runner=NS(worker=worker))
        service._collect_segments([value.source_info.path],1,10,'')
    else:
        from dragontools.worker import quality_compare_service as module
        monkeypatch.setattr(module,'analyze_media',analyzer)
        service=module.QualityCompareService(tools=NS(),metrics=NS(worker=worker,measure_comparison=lambda **k:None),
            log=lambda v:None,progress=lambda v:None,result_ready=lambda v:None,
            summary_ready=lambda v:None,is_aborted=lambda:False)
        service.run(file_a=value.source_info.path,file_b=value.target_info.path,sample_count=1,
            sample_duration_s=10,manual_ranges='',offset_b_s=0)
    assert worker in observed


def test_invalid_quality_run_restores_start_controls(qtbot,tmp_path,monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    from dragontools.gui.quality_tester_widget import QualityTesterWidget
    monkeypatch.setattr(QMessageBox,'warning',lambda *a:0)
    widget=QualityTesterWidget(); qtbot.addWidget(widget)
    video=tmp_path/'video.mkv'; video.write_bytes(b'video'); widget._add_paths([str(video)])
    widget.run_table.item(0,widget.RUN_COL_CODEC).setText('invalid-codec')
    widget._start()
    assert widget._worker is None
    assert widget.start_btn.isEnabled()


def test_modal_quality_comparison_is_discoverable_during_shutdown(qtbot):
    from PyQt6.QtCore import QThread
    from dragontools.gui.quality_tester_widget import QualityTesterWidget
    from dragontools.gui.quality_file_compare_dialog import QualityFileCompareDialog
    widget=QualityTesterWidget(); qtbot.addWidget(widget)
    dialog=QualityFileCompareDialog(widget); worker=QThread(dialog); dialog._worker=worker
    assert worker in widget.iter_shutdown_workers()
    dialog._worker=None


def test_compare_escape_cannot_hide_active_worker(qtbot,monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    from dragontools.gui.quality_file_compare_dialog import QualityFileCompareDialog
    monkeypatch.setattr(QMessageBox,'information',lambda *a:0)
    dialog=QualityFileCompareDialog(); qtbot.addWidget(dialog); dialog.show()
    dialog._worker=NS(isRunning=lambda:True)
    dialog.reject()
    assert dialog.isVisible()
    dialog._worker=None


def test_quality_native_callbacks_stay_on_gui_thread_and_release_owner(qtbot,tmp_path):
    from PyQt6.QtCore import QThread
    from PyQt6.QtWidgets import QWidget,QApplication
    from dragontools.gui.quality_worker_lifecycle import start_owned_quality_worker,connect_quality_worker,active_quality_workers
    from dragontools.worker.quality_test_thread import QualityTestThread
    host=QWidget(); qtbot.addWidget(host); host._worker=None
    worker=QualityTestThread([],str(tmp_path),[{'name':'Test'}])
    events=[]
    worker._run=lambda:worker.result_ready.emit(NS(value='from worker'))
    def wire(candidate):
        connect_quality_worker(host,candidate,result_ready=lambda result:events.append((result.value,QThread.currentThread())),
            finished=lambda:setattr(host,'_worker',None))
    start_owned_quality_worker(host,factory=lambda:worker,wire=wire,set_running=lambda v:None,report_error=lambda e:pytest.fail(e))
    qtbot.waitUntil(lambda:host._worker is None)
    assert events==[('from worker',QApplication.instance().thread())]
    assert worker not in active_quality_workers()


def test_quality_start_reservation_can_be_cancelled_before_native_start(qtbot):
    from PyQt6.QtCore import QThread
    from PyQt6.QtWidgets import QWidget
    from dragontools.gui.quality_worker_lifecycle import start_owned_quality_worker,active_quality_workers
    host=QWidget(); qtbot.addWidget(host); host._worker=None
    worker=QThread(); controls=[]; errors=[]
    def factory():
        assert host._worker in active_quality_workers()
        host._worker.cancel()
        return worker
    start_owned_quality_worker(host,factory=factory,wire=lambda w:None,set_running=controls.append,report_error=errors.append)
    assert host._worker is None and controls==[True,False]
    assert errors and 'abgebrochen' in errors[0]
    assert worker not in active_quality_workers()


def test_stale_native_quality_signal_cannot_mutate_new_worker(qtbot):
    from PyQt6.QtCore import QThread,pyqtSignal
    from PyQt6.QtWidgets import QWidget
    from dragontools.gui.quality_worker_lifecycle import connect_quality_worker
    class Worker(QThread):
        result_ready=pyqtSignal(object)
    host=QWidget(); qtbot.addWidget(host)
    old,new=Worker(host),Worker(host); host._worker=old; events=[]
    connect_quality_worker(host,old,result_ready=events.append,finished=lambda:events.append('old finished'))
    host._worker=new
    old.result_ready.emit('stale'); old.finished.emit()
    assert events==[] and host._worker is new
    host._worker=None


def test_coarse_match_is_retained_when_refinement_has_lower_similarity(monkeypatch):
    from dragontools.core.audio_video_frame_analysis import FrameExtractor,FrameMatcher
    from dragontools.core.audio_video_match_models import FrameSignature
    matcher=FrameMatcher(FrameExtractor('ffmpeg'))
    values=iter([MatchPoint(10,12,.98,98),MatchPoint(10,12.1,.70,70)])
    monkeypatch.setattr(matcher,'_find_best_in_window',lambda *a,**k:next(values))
    result=matcher.find_match('source',FrameSignature(10,0,80,80),expected_time_s=12,source_duration_s=60,search_window_s=5)
    assert result is not None and result.matched_time_s==12 and result.similarity==.98


@pytest.mark.parametrize('encoder,key,preset,flag',[
    ('nvenc','cq','p6','-cq'),('qsv','q','medium','-global_quality'),('amf','qp','balanced','-qp_i')])
def test_quality_run_fields_override_stale_backend_quality(encoder,key,preset,flag):
    from dragontools.worker.quality_test_service import QualityTestService
    test_run=QualityTestRun('Test',encoder=encoder,quality=21,preset=preset,
        encoder_options={'encoder':encoder,key:35,'preset':'other','quality':'speed'})
    args=QualityTestService.video_args(test_run)
    assert args[args.index(flag)+1]=='21'
    if encoder=='amf': assert args[args.index('-quality')+1]==preset
    else: assert args[args.index('-preset')+1]==preset


@pytest.mark.parametrize('field',['codec','encoder'])
def test_quality_run_never_silently_falls_back_for_unknown_backend(field):
    from dragontools.worker.quality_test_service import QualityTestService
    test_run=QualityTestRun('Test'); setattr(test_run,field,'unknown')
    with pytest.raises(ValueError): QualityTestService.video_args(test_run)


def test_quality_extra_args_preserve_windows_paths_and_grouping_quotes():
    import os
    from dragontools.core.quality_tester import parse_extra_args
    if os.name!='nt': pytest.skip('Native Windows argument syntax')
    assert parse_extra_args(r'-filter_script C:\Videos\filter.txt -metadata "title=Test ä"')==[
        '-filter_script',r'C:\Videos\filter.txt','-metadata','title=Test ä']


def test_audio_only_media_is_not_a_successful_video_comparison(tmp_path,monkeypatch,qapp):
    from dragontools.worker import quality_compare_service as module
    from dragontools.worker.quality_compare_thread import QualityCompareThread
    a,b=tmp_path/'a.mkv',tmp_path/'b.mkv'; a.write_bytes(b'a'); b.write_bytes(b'b')
    monkeypatch.setattr(module,'analyze_media',lambda *a,**k:NS(primary_video=None,video_streams=[],duration_s=60))
    worker=QualityCompareThread(str(a),str(b),sample_count=1)
    worker._service._metrics=NS(measure_comparison=lambda **k:None)
    worker.run()
    assert worker.outcome=='error'


def test_manual_source_visual_check_keeps_gui_responsive(qtbot,tmp_path,monkeypatch):
    import threading
    from PyQt6.QtCore import QThread,QTimer,pyqtSlot
    from PyQt6.QtWidgets import QWidget,QApplication
    from dragontools.gui.convert_widget_source_visual_actions import ConvertWidgetSourceVisualActionsMixin
    from dragontools.worker.source_visual_thread import SourceVisualCheckService
    from dragontools.worker.source_visual_models import SourceVisualCheckResult,SourceVisualCheckSettings
    entered,release=threading.Event(),threading.Event(); events=[]
    def check(*a):
        entered.set()
        assert release.wait(2)
        return SourceVisualCheckResult(enabled=True)
    monkeypatch.setattr(SourceVisualCheckService,'check',check)
    class Host(ConvertWidgetSourceVisualActionsMixin,QWidget):
        def _source_visual_settings_for_manual_check(self): return SourceVisualCheckSettings(enabled=True)
        def _log(self,*a): pass
        @pyqtSlot(object)
        def _source_visual_result_ready(self,result): events.append(QThread.currentThread())
    host=Host(); qtbot.addWidget(host)
    try:
        host._show_source_visual_check(str(tmp_path/'video.mkv'))
        qtbot.waitUntil(entered.is_set)
        heartbeat=[]; QTimer.singleShot(0,lambda:heartbeat.append(True))
        qtbot.waitUntil(lambda:bool(heartbeat))
        assert not events
    finally:
        release.set()
    qtbot.waitUntil(lambda:host._source_visual_check_thread is None)
    assert events==[QApplication.instance().thread()]


@pytest.mark.parametrize('defect',['missing_dv','wrong_dv_profile','missing_hdrplus'])
def test_av_copy_contract_rejects_lost_dynamic_hdr(defect):
    from dragontools.worker.audio_video_output_contract import require_preserved_target
    from dragontools.worker.output_probe import OutputProbeData
    video={'codec_type':'video','codec_name':'hevc','width':64,'height':36,'pix_fmt':'yuv420p10le',
        'color_transfer':'smpte2084','color_primaries':'bt2020',
        'side_data_list':[{'side_data_type':'DOVI configuration record','dv_profile':8,'dv_level':6}]}
    encoded=deepcopy(video)
    if defect=='missing_dv': encoded['side_data_list']=[]
    if defect=='wrong_dv_profile': encoded['side_data_list'][0]['dv_profile']=5
    if defect=='missing_hdrplus':
        video['side_data_list']=[{'side_data_type':'HDR Dynamic Metadata SMPTE2094-40 (HDR10+)'}]
        encoded['side_data_list']=[]
    audio={'codec_type':'audio','codec_name':'aac','channels':2,'tags':{'language':'deu'},'disposition':{'default':1}}
    target=OutputProbeData('matroska,webm',60,(video,))
    output=OutputProbeData('matroska,webm',60,(encoded,audio))
    with pytest.raises(RuntimeError):
        require_preserved_target(output,target,NS(target_codec='aac',target_language='de'),2)


def test_quality_late_conflict_preserves_verified_private_sample(tmp_path,monkeypatch):
    from dragontools.core.quality_tester import quality_output_name
    service=quality_service(); run=QualityTestRun('CPU'); segment=QualitySegment(0,10,'01')
    output=tmp_path/quality_output_name('input.mkv',run,segment)
    emitted=[]; service._result_ready=emitted.append
    monkeypatch.setattr(service,'encode_segment',lambda i,o,r,s:Path(o).write_bytes(b'verified sample'))
    def analyze(i,o,r,s):
        output.write_bytes(b'foreign')
        return NS(output_path=o)
    monkeypatch.setattr(service,'analyze_result',analyze)
    service._run_case('input.mkv',tmp_path,run,segment)
    assert output.read_bytes()==b'foreign' and not emitted
    saved=list(tmp_path.glob('.__dragontools_quality_*/'+output.name))
    assert len(saved)==1 and saved[0].read_bytes()==b'verified sample'


@pytest.mark.parametrize('defect',['modified_stage','cancel_during_hash','modified_destination'])
def test_verified_workspace_does_not_report_success_after_late_changes(tmp_path,monkeypatch,defect):
    from dragontools.worker import utility_output_workspace as module
    workspace=module.VerifiedOutputWorkspace(tmp_path,lambda *a:None)
    destination=tmp_path/'final.mkv'
    calls=[]
    with workspace as root:
        stage=root/'sample.mkv'; stage.write_bytes(b'verified')
        workspace.mark_verified(stage)
        def current():
            calls.append(True)
            if defect=='cancel_during_hash' and len(calls)==2: raise RuntimeError('cancelled')
        if defect=='modified_stage': stage.write_bytes(b'foreign')
        if defect=='modified_destination':
            original=module.publish_staged_no_replace
            def publish(a,b):
                original(a,b); Path(b).write_bytes(b'foreign')
            monkeypatch.setattr(module,'publish_staged_no_replace',publish)
        with pytest.raises(RuntimeError): workspace.publish_verified(stage,destination,require_current=current)
        assert not workspace.published
    if defect=='modified_destination': assert destination.read_bytes()==b'foreign'
    else: assert not destination.exists() and stage.is_file()


def test_matcher_rechecks_analyzed_input_after_output_validation(tmp_path,monkeypatch):
    from dragontools.worker import audio_video_match_create_service as module
    from dragontools.core.transaction_identity import stat_identity
    value=mapping(tmp_path)
    value.source_info.file_identity=tuple(stat_identity(value.source_info.path))
    stage=tmp_path/'staged.mkv'; stage.write_bytes(b'verified')
    output=tmp_path/'final.mkv'
    def validate(*a,**k):
        Path(value.source_info.path).write_bytes(b'changed during validation')
        return 60
    monkeypatch.setattr(module,'validate_output',validate)
    with pytest.raises(RuntimeError,match='verändert'):
        create_service()._validate_and_commit(value,stage,output,target_path=value.target_info.path)
    assert stage.read_bytes()==b'verified' and not output.exists()
