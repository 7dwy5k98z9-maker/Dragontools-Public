"""Characterize dispatch and reproduce per-job ownership/shutdown boundaries."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as NS
import threading

import pytest

from dragontools.gui.preflight_metadata_apply import apply_metadata_result
from dragontools.tests.test_patch05_second_review import _service, _media
from dragontools.worker.postprocess_async import AsyncPostProcessCoordinator
from dragontools.worker.postprocess_models import PostProcessRunResult


@pytest.mark.parametrize('suggestion,method,args,kwargs', [
    ({'__error__':'failure'},'mark_metadata_lookup_failed',('failure',),{}),
    ({'__existing_series_dir__':'dir','base':'root','series_name':'Series'},'apply_existing_series_dir',('dir','root','Series','','folder_search',''),{}),
    ({'__existing_movie_dir__':'dir','movie_name':'Film'},'apply_existing_movie_dir',('dir','','Film','database',''),{}),
    ({'__movie_library_warning__':'warn','movie_name':'Film'},'apply_unusable_movie_match',(),{'message':'warn','movie_name':'Film'}),
    ({'__library_path_warning__':'warn','series_name':'Series'},'apply_unusable_library_series_match',(),{'message':'warn','series_name':'Series','suggested_series_name':'','base':'','base_type':''}),
    ({'__series_dir_choices__':[{'path':'dir'}]},'apply_existing_series_dir_choices',(),{'choices':[{'path':'dir'}],'series_name':'','suggested_series_name':''}),
    ({'__local_series_missing__':True},'mark_existing_series_dir_not_found',(),{}),
    ({'title':'Film'},'apply_online_metadata_suggestion',({'title':'Film'},),{}),
    ({'__error__':'failure','__existing_movie_dir__':'dir'},'mark_metadata_lookup_failed',('failure',),{}),
])
def test_metadata_dispatch_preserves_payload_defaults_and_priority(suggestion,method,args,kwargs):
    events=[]
    widget=NS(**{method:lambda *a,**kw:events.append((a,kw))})
    apply_metadata_result(widget,suggestion)
    assert events==[(args,kwargs)]


def test_online_series_remains_authoritative_after_library_warning():
    events=[]; online={'title':'Online','year':2024}
    widget=NS(mark_library_path_warning=lambda m:events.append(('warning',m)),
        apply_online_metadata_suggestion=lambda s:events.append(('online',s)))
    apply_metadata_result(widget,{'__library_path_warning__':'offline','__online_series_suggestion__':online})
    assert events==[('warning','offline'),('online',online)]


@pytest.mark.parametrize('marker',['__error__','__existing_series_dir__','__existing_movie_dir__','__movie_library_warning__','__library_path_warning__','__series_dir_choices__','__local_series_missing__'])
def test_known_metadata_events_without_optional_receiver_do_not_become_online(marker):
    events=[]
    apply_metadata_result(NS(apply_online_metadata_suggestion=events.append),{marker:'value'})
    assert not events


def test_encode_defaults_are_owned_at_construction():
    original={'autocrop_enabled':False,'nested':{'label':'planned'}}
    service=_service(original)
    original['nested']['label']='foreign'; original['encoder']='nvenc'
    plan=service.prepare_encode_plan('source.mkv','out.mkv',_media(),'standard','mkv',{})
    assert plan.encoder_options['nested']=={'label':'planned'}
    assert 'encoder' not in plan.encoder_options


def test_detection_cannot_change_the_subtitle_override_for_this_plan():
    override={'subtitle_settings':{'mode':'chosen'}}
    def detector(*args): override['subtitle_settings']['mode']='foreign'
    service=_service(crop=detector); seen=[]
    service._stream_args=NS(sub_args=lambda p,mi,ov,c:(seen.append(deepcopy(ov)) or ([],['-sn'])),
        build_vf_args=lambda *a,**kw:[],audio_args=lambda *a:[],audio_input_args=lambda *a:[])
    service.prepare_encode_plan('source.mkv','out.mkv',_media(),'standard','mkv',override)
    assert seen==[{'subtitle_settings':{'mode':'chosen'}}]


@pytest.mark.parametrize('options,override,crop_calls,imax_calls', [
    ({},{'imax':True},0,0),
    ({'autocrop_enabled':False},{},0,0),
    ({'imax_auto_detect':True},{},0,1),
    ({'autocrop_mode':'multi','autocrop_probe_start_s':0},{},1,0),
])
def test_geometry_dispatch_keeps_imax_crop_and_zero_start_policy(options,override,crop_calls,imax_calls):
    crop=[]; imax=[]
    service=_service(options,lambda *a:crop.append(a) or None)
    service._detect_imax_auto=lambda *a:imax.append(a) or True
    plan=service.prepare_encode_plan('source.mkv','out.mkv',_media(),'standard','mkv',override)
    assert len(crop)==crop_calls and len(imax)==imax_calls and plan.crop is None
    if crop_calls:
        assert crop[0][3:] == ('multi',0,45,600,1.0)


def test_shutdown_failure_is_visible_to_every_waiter():
    coordinator=_coordinator()
    real_shutdown=coordinator._executor.shutdown
    def fail(**kw): raise RuntimeError('executor did not finish')
    coordinator._executor.shutdown=fail
    try:
        for _ in range(2):
            with pytest.raises(RuntimeError,match='executor did not finish'):
                coordinator.wait_for_all()
    finally:
        real_shutdown(wait=True)


def test_move_result_keeps_legacy_schema_and_fresh_mutable_fields():
    from dragontools.core.move_file_service import new_move_result
    result=new_move_result('input/Film.mkv','output',dest_name='Renamed.mp4')
    assert result['source_path']=='input/Film.mkv'
    assert result['dest_path']==str(Path('output/Renamed.mp4'))
    assert result['replacement_artifacts_by_type']=={'nfo':0,'trickplay':0}
    result['replacement_artifact_paths'].append('foreign')
    assert new_move_result('a.mkv','output')['replacement_artifact_paths']==[]


def _coordinator():
    return AsyncPostProcessCoordinator(settings=None,tools=None,log=None,
        service_factory=lambda:NS(run_result=lambda **kw:PostProcessRunResult([],[])))


def test_every_shutdown_waiter_waits_for_the_actual_executor_finish():
    coordinator=_coordinator(); entered=threading.Event(); release=threading.Event(); returned=threading.Event()
    real_shutdown=coordinator._executor.shutdown
    def shutdown(**kw):
        entered.set(); assert release.wait(5); real_shutdown(**kw)
    coordinator._executor.shutdown=shutdown
    first=threading.Thread(target=coordinator.wait_for_all)
    second=threading.Thread(target=lambda:(coordinator.wait_for_all(),returned.set()))
    first.start()
    try:
        assert entered.wait(3); second.start()
        assert not returned.wait(.15), 'Second caller reports shutdown before executor finished'
    finally:
        release.set(); first.join(5)
        if second.ident is not None: second.join(5)
        coordinator.wait_for_all()
    assert returned.is_set() and not first.is_alive() and not second.is_alive()


def test_shutdown_waits_for_pending_announcement_and_completion_registration():
    coordinator=_coordinator(); pending=threading.Event(); release=threading.Event(); drained=threading.Event(); events=[]
    def emit_result(src,dst,status):
        if status=='🧩': pending.set(); assert release.wait(5)
        events.append(status)
    submit=threading.Thread(target=lambda:coordinator.submit(input_path='in',output_path='out',existing_sidecars=[],
        sidecar_outputs={},postprocess_outputs={},result_service=NS(emit_file_result=emit_result,emit_file_progress=lambda *a:None)))
    drain=threading.Thread(target=lambda:(coordinator.wait_for_all(),drained.set()))
    submit.start()
    try:
        assert pending.wait(3); drain.start()
        assert not drained.wait(.15), 'Future done alone does not mean terminal callback delivered'
    finally:
        release.set(); submit.join(5)
        if drain.ident is not None: drain.join(5)
        coordinator.wait_for_all()
    assert events==['🧩','✅'] and drained.is_set()


def test_selected_responsibilities_do_not_depend_back_on_the_facade():
    import ast
    root=Path(__file__).resolve().parents[1]
    tree=ast.parse((root/'core/move_preparation.py').read_text(encoding='utf-8'))
    assert not any(isinstance(n,ast.ImportFrom) and (n.module or '').endswith('move_file_service') for n in ast.walk(tree))


@pytest.mark.parametrize('relative',['gui/preflight_metadata_apply.py','worker/encode_plan_service.py'])
def test_selected_policy_orchestrators_have_no_unresolved_structural_risk(relative):
    from dragontools.tests.responsibility_checks import structural_risks
    root=Path(__file__).resolve().parents[1]
    assert not structural_risks((root/relative).read_text(encoding='utf-8'))
