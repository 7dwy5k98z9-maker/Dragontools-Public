from pathlib import Path
from types import SimpleNamespace as NS
import json
import pytest
from dragontools.worker.dv_pipeline_stages import DVPipelineStages
from dragontools.worker.dv_runtime_models import DVTempState
from dataclasses import replace
from dragontools.worker.workflow_models import PipelineExecutionResult
from dragontools.tests.test_dv_corrupt_rpu_fallback import _ctx,_services
from dragontools.worker.dv_source_rpu_fallback import is_corrupt_source_rpu_failure

@pytest.mark.parametrize('video,rpu,expected',[(155504,155504,True),(155504,20,False),(155504,155503,True),(1,1,True)])
def test_extracted_source_is_checked_before_encode(tmp_path,monkeypatch,video,rpu,expected):
    import dragontools.worker.dv_pipeline_stages as stages
    source=tmp_path/'original.mkv';source.write_bytes(b'original')
    rpu_path=tmp_path/'source.rpu';rpu_path.write_bytes(b'rpu')
    owner=DVPipelineStages.__new__(DVPipelineStages)
    owner._tools=NS(ffprobe='ffprobe',dovi_tool='dovi_tool')
    owner._temp_state=DVTempState();owner._log=lambda *a:None
    owner._probe_rpu_frame_count=lambda runner,path:rpu
    monkeypatch.setattr(stages,'_video_service',lambda _:NS(extract_rpu=lambda *a:True))
    media=NS(primary_video=NS(index=3),video_streams=[NS(index=0),NS(index=3)])
    state=NS(request=NS(input_path=str(source),media_info=media),files=NS(rpu_orig=rpu_path))
    calls=[]
    def run(cmd,**kwargs):
        calls.append(cmd)
        return NS(returncode=0,stdout=json.dumps({'streams':[{'index':3,'codec_type':'video','tags':{'NUMBER_OF_FRAMES':str(video)}}]}),stderr='')
    assert owner._extract_rpu(state,NS(run=run)) is expected
    assert calls and '-count_frames' not in calls[0]
    assert calls[0][calls[0].index('-select_streams')+1]=='3'
    assert source.read_bytes()==b'original'
    if not expected:
        assert owner._temp_state.failure_stage=='DV SOURCE-RPU-CHECK'
        assert owner._temp_state.failure_reason.startswith('SOURCE_RPU_UNUSABLE:') is (rpu==20)

@pytest.mark.parametrize('hdrplus',[False,True])
@pytest.mark.parametrize('enabled',[False,True])
def test_early_failure_replans_once_preserving_other_policy(hdrplus,enabled):
    failure=PipelineExecutionResult(False,failure_stage='DV SOURCE-RPU-CHECK',
        failure_reason='SOURCE_RPU_UNUSABLE: Video=155504 RPU=20')
    svc,temp,logger,planning,executor=_services(failure,PipelineExecutionResult.succeeded())
    svc._config=replace(svc._config,corrupt_source_rpu_fallback=enabled)
    ctx=_ctx(has_hdrplus=hdrplus,preserve_hdrplus=hdrplus)
    override={'encoder_profile':{'encoder_options':{'preserve_dv':True}},'audio_mode':'custom',
        'subtitle_tracks':[{'index':12,'keep':True}],'quality_target':88}
    if enabled:
        svc.process(ctx,override)
        assert [r.pipeline for r in executor.requests]==['dv','hdrplus' if hdrplus else 'standard']
        assert len(planning.overrides)==1
        assert executor.requests[-1].override=={**override,'preserve_dv':False}
        assert executor.requests[-1].preserve_hdrplus is hdrplus
    else:
        with pytest.raises(RuntimeError,match='SOURCE_RPU_UNUSABLE'):svc.process(ctx,override)
        assert len(executor.requests)==1 and not planning.overrides
    assert 'preserve_dv' not in override

def test_cancel_during_fallback_does_not_start_second_pipeline():
    failure=PipelineExecutionResult(False,failure_stage='DV SOURCE-RPU-CHECK',
        failure_reason='SOURCE_RPU_UNUSABLE: Video=155504 RPU=20')
    svc,temp,logger,planning,executor=_services(failure)
    svc._abort_check=lambda:True
    with pytest.raises(RuntimeError,match='Abgebrochen'):svc.process(_ctx(),{})
    assert len(executor.requests)==1 and not planning.overrides

@pytest.mark.parametrize('stage,reason,output,expected',[
    ('DV SOURCE-RPU-CHECK','Quellvideo/RPU-Frameabweichung: 155504/155503','',False),
    ('STEP 4/7 Frame-Recovery','RPU/Encode-Frame-Mismatch','',False),
    ('STEP 3/7 RPU-Extraktion','Tool failed','No track found for ID 0',False),
    ('STEP 3/7 RPU-Extraktion','Tool failed','Error: Invalid RPU last byte: 248',True)])
def test_source_corruption_is_separate_from_track_and_post_encode_errors(stage,reason,output,expected):
    result=PipelineExecutionResult(False,failure_stage=stage,failure_reason=reason,
        tool='dovi_tool.exe',command='dovi_tool.exe extract-rpu -i original.mkv -o source.rpu',tool_output=output)
    assert is_corrupt_source_rpu_failure(result,DVTempState()) is expected

@pytest.mark.parametrize('rows,stderr,aborted',[
    ([], '',False),([{'index':0,'nb_read_frames':'155504'}],'',False),
    ([{'index':3,'nb_frames':'N/A'}],'',False),
    ([{'index':3,'nb_read_frames':'155504'}],'Decoder error',False),
    ([{'index':3,'codec_type':'video','nb_read_frames':'155504'}],'',True),
    ([{'index':3,'codec_type':'audio','nb_read_frames':'155504'}],'',False)])
def test_unknown_wrong_track_decoder_error_and_cancel_never_trigger_fallback(tmp_path,rows,stderr,aborted):
    from dragontools.worker.dv_source_rpu_check import SourceRpuSanityCheck
    src=tmp_path/'source.mkv';src.write_bytes(b'source');rpu=tmp_path/'source.rpu';rpu.write_bytes(b'rpu')
    temp=DVTempState();check=SourceRpuSanityCheck(tools=NS(ffprobe='ffprobe'),temp_state=temp,log=lambda *a:None)
    state=NS(request=NS(input_path=str(src),media_info=NS(primary_video=NS(index=3))),files=NS(rpu_orig=rpu))
    runner=NS(run=lambda *a,**kw:NS(returncode=0,stdout=json.dumps({'streams':rows}),stderr=stderr,aborted=aborted))
    assert not check.validate(state,runner,probe_rpu=lambda *a:20)
    assert not temp.failure_reason.startswith('SOURCE_RPU_UNUSABLE:')

def test_fallback_setting_roundtrip_and_focused_dialog_isolation(tmp_path,qapp,monkeypatch):
    from PyQt6.QtCore import QSettings
    import dragontools.gui.settings_dialog as module
    from dragontools.core.settings_conversion import SET_KEY_CORRUPT_SOURCE_RPU_FALLBACK as key
    settings=QSettings(str(tmp_path/'settings.ini'),QSettings.Format.IniFormat)
    settings.setValue(key,'false')
    monkeypatch.setattr(module,'QSettings',lambda *a:settings)
    dialog=module.SettingsDialog(visible_sections=('source_visual',))
    assert not dialog.corrupt_rpu_fallback_cb.isChecked()
    dialog.corrupt_rpu_fallback_cb.setChecked(True)
    assert dialog._active_sections()[0].save()
    assert settings.value(key,type=bool) is True
    dialog.reject()
    focused=module.SettingsDialog(visible_sections=('media_library',))
    focused.corrupt_rpu_fallback_cb.setChecked(False)
    assert focused._active_sections()[0].save()
    assert settings.value(key,type=bool) is True
    focused.reject()

def test_av1_source_failure_uses_the_same_configurable_fallback():
    result=PipelineExecutionResult(False,failure_stage='DV SOURCE-RPU-CHECK',failure_reason='SOURCE_RPU_UNUSABLE: 60/10')
    svc,*_= _services(result)
    assert svc._corrupt_source_rpu_requires_fallback(NS(pipeline='av1_dv'),result)
    svc._config=replace(svc._config,corrupt_source_rpu_fallback=False)
    assert not svc._corrupt_source_rpu_requires_fallback(NS(pipeline='av1_dv'),result)

@pytest.mark.parametrize('direct',[False,True])
def test_mp4_subtitle_boundary_rejects_complete_source_containers(direct):
    from dragontools.worker.mp4box_track_args import append_mp4box_subtitle
    command=['MP4Box','-new','output.mp4','-add','processed.hevc']
    before=list(command)
    with pytest.raises(ValueError,match='Quellcontainer'):
        append_mp4box_subtitle(command,NS(path=Path('original.mkv'),source_direct=direct))
    assert command==before


@pytest.mark.parametrize('rows,video,rpu,expected',[
    ({'nb_frames':'144000'},NS(),20,False),
    ({'tags':{'NUMBER_OF_FRAMES':'144000'}},NS(),144000,True),
    ({'tags':{'DURATION':'01:40:00.000'},'avg_frame_rate':'24/1'},NS(),144060,True),
    ({'duration':'6000','avg_frame_rate':'24000/1001'},NS(),143856,True),
    ({'duration':'6000','avg_frame_rate':'24/1'},NS(),143900,True),
    ({'duration':'6000','avg_frame_rate':'24/1'},NS(),20,False),
    ({'duration':'6000','avg_frame_rate':'24/1'},NS(),0,False),
    ({'duration':'6000','avg_frame_rate':'24/1'},NS(),200000,False),
    ({'nb_frames':'60'},NS(),10,False),
    ({'nb_frames':'N/A','duration':'N/A','avg_frame_rate':'0/0'},NS(),20,True),
    ({'duration':'6000','avg_frame_rate':'24/1'},NS(frame_rate_mode='VFR'),20,True),
])
def test_fast_source_plausibility_uses_metadata_and_estimates(tmp_path,rows,video,rpu,expected):
    from dragontools.worker.dv_source_rpu_check import SourceRpuSanityCheck
    source=tmp_path/'source.mkv';source.write_bytes(b'video')
    path=tmp_path/'metadata.rpu';path.write_bytes(b'metadata')
    video.index=3
    state=NS(request=NS(input_path=str(source),media_info=NS(primary_video=video)),files=NS(rpu_orig=path))
    temp=DVTempState();calls=[];logs=[]
    def run(command,**kwargs):
        calls.append(command)
        assert '-count_frames' not in command and '-count_packets' not in command
        return NS(returncode=0,stdout=json.dumps({'streams':[{'index':3,'codec_type':'video',**rows}]}),stderr='')
    check=SourceRpuSanityCheck(tools=NS(ffprobe='ffprobe'),temp_state=temp,log=lambda *a:logs.append(a))
    assert check.validate(state,NS(run=run),probe_rpu=lambda *a:rpu) is expected
    assert len(calls)==1 and calls[0][calls[0].index('-select_streams')+1]=='3'
    if rpu==0 or (rpu==20 and rows.get('duration')!='N/A' and not getattr(video,'frame_rate_mode','')):
        assert temp.failure_reason.startswith('SOURCE_RPU_UNUSABLE:')
    assert source.read_bytes()==b'video'


def test_preanalysed_frame_count_avoids_another_video_probe(tmp_path):
    from dragontools.worker.dv_source_rpu_check import SourceRpuSanityCheck
    source=tmp_path/'source.mkv';source.write_bytes(b'video')
    rpu=tmp_path/'metadata.rpu';rpu.write_bytes(b'rpu')
    state=NS(request=NS(input_path=str(source),media_info=NS(primary_video=NS(index=3,frame_count=144000))),files=NS(rpu_orig=rpu))
    check=SourceRpuSanityCheck(tools=NS(),temp_state=DVTempState(),log=lambda *a:None)
    runner=NS(run=lambda *_a,**_k:pytest.fail('Known metadata must not reread source video'))
    assert check.validate(state,runner,probe_rpu=lambda *a:143940)


def test_source_plausibility_does_not_accept_an_unreadable_or_changed_rpu(tmp_path):
    from dragontools.worker.dv_source_rpu_check import SourceRpuSanityCheck
    source=tmp_path/'source.mkv';source.write_bytes(b'video')
    rpu=tmp_path/'metadata.rpu';rpu.write_bytes(b'rpu')
    state=NS(request=NS(input_path=str(source),media_info=NS(primary_video=NS(index=3,frame_count=144000))),files=NS(rpu_orig=rpu))
    temp=DVTempState();check=SourceRpuSanityCheck(tools=NS(),temp_state=temp,log=lambda *a:None)
    assert not check.validate(state,NS(),probe_rpu=lambda *a:None)
    assert not temp.failure_reason.startswith('SOURCE_RPU_UNUSABLE:')
    def changed(*args):
        rpu.write_bytes(b'changed RPU contents')
        return 144000
    assert not check.validate(state,NS(),probe_rpu=changed)
    assert not temp.failure_reason.startswith('SOURCE_RPU_UNUSABLE:')


def test_source_plausibility_keeps_default_exact_count_contract():
    from dragontools.worker.dv_source_rpu_check import SourceRpuSanityCheck
    check=SourceRpuSanityCheck(tools=NS(),temp_state=DVTempState(),log=lambda *a:None)
    assert check.validate_counts(144000,143940,plausibility=True)
    assert not check.validate_counts(144000,143940)
