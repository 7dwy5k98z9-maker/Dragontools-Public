"""Publication and callback ownership for optional postprocessing."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace as NS
import threading

import pytest

from dragontools.tests.test_review14_postprocess_jellyfin import DummySettings


def test_nfo_skip_does_not_replace_a_late_foreign_target(tmp_path):
    from dragontools.worker.nfo_commit import plan_nfo_target,commit_nfo
    target=tmp_path/'film.nfo';plan=plan_nfo_target(target,'skip')
    def writer(path):
        target.write_bytes(b'FOREIGN')
        Path(path).write_bytes(b'GENERATED')
    with pytest.raises(FileExistsError):
        commit_nfo(plan,writer)
    assert target.read_bytes()==b'FOREIGN'


def test_invalid_nfo_conflict_mode_is_not_overwrite(tmp_path):
    from dragontools.worker.nfo_commit import plan_nfo_target
    target=tmp_path/'film.nfo';target.write_bytes(b'EXISTING')
    plan=plan_nfo_target(target,'overwriet')
    assert not plan.should_write and plan.conflict_mode=='skip'


@pytest.mark.parametrize('alias',['video','target'])
def test_prepared_nfo_cleanup_cannot_delete_media_or_final_nfo(tmp_path,alias):
    from dragontools.worker.postprocess_models import PreparedNfo
    from dragontools.worker.postprocess_runner import PostProcessService
    video=tmp_path/'film.mkv';target=video.with_suffix('.nfo')
    video.write_bytes(b'MEDIA');target.write_bytes(b'USER-NFO')
    stage=video if alias=='video' else target
    prepared=PreparedNfo(str(stage),str(target),'overwrite','movie',object())
    service=PostProcessService(settings=None,tools=NS(),log=None)
    result=service.commit_prepared_nfo(prepared,final_output_path=str(video))
    assert result.items[0]['status']=='error'
    assert video.read_bytes()==b'MEDIA' and target.read_bytes()==b'USER-NFO'


def test_prepared_nfo_is_not_published_without_installed_video(tmp_path):
    from dragontools.worker.postprocess_models import PreparedNfo
    from dragontools.worker.postprocess_runner import PostProcessService
    stage=tmp_path/'.prepared.nfo';stage.write_text('<movie><title>Generated</title></movie>',encoding='utf-8')
    video=tmp_path/'absent.mkv'
    result=PostProcessService(settings=None,tools=NS(),log=None).commit_prepared_nfo(
        PreparedNfo(str(stage),str(video.with_suffix('.nfo')),'skip','movie',object()),final_output_path=str(video))
    assert not result.created_paths and not video.with_suffix('.nfo').exists()


def test_progress_callback_failure_still_delivers_terminal_result(tmp_path):
    from dragontools.worker.postprocess_async import AsyncPostProcessCoordinator
    from dragontools.worker.postprocess_models import PostProcessRunResult
    events=[]
    def broken(*_):raise RuntimeError('progress unavailable')
    result_service=NS(emit_file_progress=broken,emit_file_result=lambda *a:events.append(a))
    coordinator=AsyncPostProcessCoordinator(settings=None,tools=None,log=None,
        service_factory=lambda:NS(run_result=lambda **kw:PostProcessRunResult([],[])))
    try:
        assert coordinator.submit(input_path='source',output_path=str(tmp_path/'out.mkv'),
            existing_sidecars=[],sidecar_outputs={},postprocess_outputs={},result_service=result_service)
        coordinator.wait_for_all()
    finally:
        coordinator.wait_for_all()
    assert events[-1][-1]=='✅' and sum(e[-1]=='✅' for e in events)==1


def test_trickplay_staging_does_not_remove_an_existing_partial_directory(tmp_path,monkeypatch):
    from dragontools.worker.trickplay_service import TrickplayGenerator,TrickplaySettings
    video=tmp_path/'film.mkv';video.write_bytes(b'SOURCE')
    old_partial=tmp_path/'film.trickplay.__partial__';old_partial.mkdir()
    evidence=old_partial/'recovery.bin';evidence.write_bytes(b'FOREIGN-RECOVERY')
    monkeypatch.setattr(TrickplayGenerator,'_render_sprites',lambda *a:'')
    assert TrickplayGenerator(ffmpeg_path='ffmpeg',log=None).generate(video,TrickplaySettings(enabled=True)) is None
    assert evidence.read_bytes()==b'FOREIGN-RECOVERY'


def test_trickplay_abort_after_render_prevents_publication(tmp_path,monkeypatch):
    from dragontools.worker.trickplay_service import TrickplayGenerator,TrickplaySettings
    video=tmp_path/'film.mkv';video.write_bytes(b'SOURCE')
    worker=NS(abort_requested=False,abort_type='sofort')
    def render(self,source,settings,path):
        (path/'0.jpg').write_bytes(b'fixture image')
        worker.abort_requested=True
        return 'rendered'
    monkeypatch.setattr(TrickplayGenerator,'_render_sprites',render)
    result=TrickplayGenerator(ffmpeg_path='ffmpeg',worker=worker,log=None).generate(
        video,TrickplaySettings(enabled=True,hwaccel='none'))
    assert result is None and not video.with_suffix('.trickplay').exists()


@pytest.mark.parametrize('ordinal',[True,1.5,'1.5',float('inf')])
def test_nfo_track_ordinal_requires_exact_integer(tmp_path,ordinal):
    from dragontools.core.nfo_stream_metadata import stage_stream_language_update,NfoStreamMetadataError
    source=tmp_path/'source.nfo';target=tmp_path/'pending.nfo'
    source.write_text('<movie><fileinfo><streamdetails><audio><language>eng</language></audio></streamdetails></fileinfo></movie>',encoding='utf-8')
    with pytest.raises(NfoStreamMetadataError):
        stage_stream_language_update(source,target,stream_type='audio',ordinal=ordinal,language='de')
    assert not target.exists()


def test_nfo_language_staging_does_not_truncate_foreign_target(tmp_path):
    from dragontools.core.nfo_stream_metadata import stage_stream_language_update
    source=tmp_path/'source.nfo';target=tmp_path/'pending.nfo'
    source.write_text('<movie><fileinfo><streamdetails><audio><language>eng</language></audio></streamdetails></fileinfo></movie>',encoding='utf-8')
    target.write_bytes(b'FOREIGN')
    with pytest.raises(FileExistsError):
        stage_stream_language_update(source,target,stream_type='audio',ordinal=1,language='de')
    assert target.read_bytes()==b'FOREIGN'


@pytest.mark.parametrize('path',['/TV/../private/movie.mkv','/TV/a/../../private/movie.mkv'])
def test_jellyfin_refresh_path_cannot_escape_a_library_root(path):
    from dragontools.core.jellyfin_refresh_service import prepare_targeted_updates
    from dragontools.core.jellyfin_api import JellyfinApiError
    with pytest.raises(JellyfinApiError):
        prepare_targeted_updates([{'Path':path,'UpdateType':'Created'}],['/TV'])


def test_jellyfin_posix_case_distinct_updates_are_not_deduplicated():
    from dragontools.core.jellyfin_refresh_service import prepare_targeted_updates
    result,_=prepare_targeted_updates([{'Path':'/TV/A.mkv','UpdateType':'Created'},
        {'Path':'/TV/a.mkv','UpdateType':'Created'}],['/TV'])
    assert len(result)==2


def test_jellyfin_windows_drive_root_is_a_valid_library():
    from dragontools.core.jellyfin_refresh_service import prepare_targeted_updates
    result,_=prepare_targeted_updates([{'Path':'C:/TV/a.mkv','UpdateType':'Created'}],['C:/'])
    assert result[-1]['Path']=='C:/TV/a.mkv'


def test_jellyfin_case_distinct_posix_mappings_are_kept():
    from dragontools.core.jellyfin_refresh_service import merge_refresh_mappings
    from dragontools.core.media_library_types import PathMapping
    result=merge_refresh_mappings([PathMapping('','/TV','C:/one')], [PathMapping('','/tv','C:/two')])
    assert len(result)==2


def test_jellyfin_full_scan_does_not_start_for_empty_installed_outputs():
    from dragontools.core.jellyfin_refresh_service import JellyfinRefreshConfig,execute_refresh
    calls=[]
    result=execute_refresh(JellyfinRefreshConfig('http://fake','key',refresh_mode='full'),[],
        client_factory=lambda *a:NS(refresh_library=lambda:calls.append('refresh')))
    assert result.update_count==0 and not calls


def test_notification_bad_summary_cannot_escape_to_conversion():
    from dragontools.core.conversion_notifications import ConversionNotificationService
    from dragontools.core.settings_notifications import SET_KEY_NOTIFICATIONS_ENABLED
    notifications=ConversionNotificationService(settings=DummySettings({SET_KEY_NOTIFICATIONS_ENABLED:True}),emit=lambda *a:True)
    notifications.on_run_finished({'ok':'invalid','errors':float('inf')})


def test_reminder_concurrent_adds_are_not_lost(tmp_path,monkeypatch):
    from dragontools.core import replacement_reminders as module
    path=tmp_path/'reminders.json';barrier=threading.Barrier(2);guard=threading.Lock();reads=[0]
    original=module._load
    def synchronized_load(target, **kwargs):
        result=original(target, **kwargs)
        with guard:reads[0]+=1;number=reads[0]
        if number<=2:
            try:barrier.wait(timeout=.3)
            except threading.BrokenBarrierError:pass
        return result
    monkeypatch.setattr(module,'_load',synchronized_load)
    def add(i):
        return module.add_replacement_reminder(series_name='series',season=1,episode=i,
            episode_label=f'S01E{i:02}',old_paths=[f'old-{i}'],new_path=f'new-{i}',reason='replace',
            path=path,now=datetime(2026,10,6))
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(add,[1,2]))
    assert len({item['id'] for item in results})==2
    assert len(module.list_replacement_reminders(path))==2


def test_source_trickplay_is_prepared_without_replacing_live_cache(tmp_path,monkeypatch):
    from dragontools.worker.postprocess_runner import PostProcessService
    from dragontools.worker.trickplay_service import TrickplayGenerator
    from dragontools.core.settings_postprocess import SET_KEY_TRICKPLAY_ENABLED,SET_KEY_TRICKPLAY_SOURCE_MODE,SET_KEY_TRICKPLAY_CONFLICT_MODE
    source=tmp_path/'film.mkv';source.write_bytes(b'ORIGINAL')
    live=tmp_path/'film.trickplay'/'320 - 10x10';live.mkdir(parents=True)
    (live/'0.jpg').write_bytes(b'ORIGINAL-CACHE')
    def fake_run(self,command):
        Path(command[-1]).parent.joinpath('0.jpg').write_bytes(b'PREPARED-CACHE')
        return True
    monkeypatch.setattr(TrickplayGenerator,'_run',fake_run)
    settings=DummySettings({SET_KEY_TRICKPLAY_ENABLED:True,SET_KEY_TRICKPLAY_SOURCE_MODE:'source',SET_KEY_TRICKPLAY_CONFLICT_MODE:'overwrite'})
    service=PostProcessService(settings=settings,tools=NS(ffmpeg='ffmpeg'),log=None)
    prepared=service.prepare_source_trickplay(input_path=str(source),output_path=str(source))
    assert (live/'0.jpg').read_bytes()==b'ORIGINAL-CACHE'
    result=service.run_result(input_path=str(source),output_path=str(source),prepared_source_trickplay=prepared)
    assert result.created_paths==[str(live.parent)]
    assert (live/'0.jpg').read_bytes()==b'PREPARED-CACHE'
    assert result.items[0]['status']=='replaced'


def test_stopped_trickplay_does_not_wait_for_busy_semaphore():
    from dragontools.worker.trickplay_concurrency import trickplay_semaphore
    from dragontools.worker.trickplay_service import TrickplayGenerator, TrickplaySettings
    import tempfile
    done=threading.Event()
    with tempfile.TemporaryDirectory() as folder:
        video=Path(folder)/'video.mkv'; video.write_bytes(b'video')
        generator=TrickplayGenerator(ffmpeg_path='ffmpeg',log=None,worker=NS(abort_requested=True))
        def run():
            try: generator.generate(video,TrickplaySettings(enabled=True,max_jobs=1))
            finally: done.set()
        with trickplay_semaphore(1):
            thread=threading.Thread(target=run);thread.start()
            stopped=done.wait(.3)
        thread.join(timeout=2)
        assert stopped and not thread.is_alive()


def test_corrupt_reminders_cannot_be_overwritten(tmp_path):
    from dragontools.core.replacement_reminders import add_replacement_reminder
    path=tmp_path/'reminders.json';path.write_bytes(b'{broken recovery data')
    with pytest.raises((ValueError, OSError)):
        add_replacement_reminder(series_name='s',season=1,episode=1,episode_label='S01E01',
            old_paths=['old'],new_path='new',reason='replace',path=path)
    assert path.read_bytes()==b'{broken recovery data'


def test_optional_jellyfin_logger_failure_does_not_escape(monkeypatch):
    from dragontools.gui import jellyfin_refresh_dispatch as module
    monkeypatch.setattr(module,'_settings_snapshot',lambda *a,**kw: (_ for _ in ()).throw(ValueError('settings')))
    def broken_log(*args): raise RuntimeError('logger')
    assert module.dispatch_after_move([],broken_log,settings=DummySettings({})) is False


def test_cancelled_semaphore_does_not_take_a_permit():
    from dragontools.worker.trickplay_concurrency import trickplay_semaphore
    with trickplay_semaphore(1):
        with pytest.raises(RuntimeError,match='[Aa]bgebrochen'):
            with trickplay_semaphore(1,abort_check=lambda:True):
                raise AssertionError('cancelled waiter received permit')


def test_trickplay_return_zero_with_invalid_jpeg_is_rejected(tmp_path,monkeypatch):
    from dragontools.worker import trickplay_service as module
    from dragontools.worker.tool_runner import ToolRunResult
    video=tmp_path/'video.mkv';video.write_bytes(b'video')
    def fake_tool(command,**kwargs):
        Path(command[-1]).parent.joinpath('0.jpg').write_bytes(b'not a JPEG')
        return ToolRunResult(command=command,returncode=0)
    monkeypatch.setattr(module,'run_tool',fake_tool)
    root=module.TrickplayGenerator(ffmpeg_path='ffmpeg',log=None).generate(video,
        module.TrickplaySettings(enabled=True,hwaccel='none'))
    assert root is None and not video.with_suffix('.trickplay').exists()


def test_notification_and_both_loggers_failing_cannot_escape(monkeypatch):
    from dragontools.core import conversion_notifications as module
    from dragontools.core.settings_notifications import SET_KEY_NOTIFICATIONS_ENABLED
    def broken(*args,**kwargs): raise RuntimeError('notification/logger unavailable')
    monkeypatch.setattr(module,'logging',NS(getLogger=lambda *a:NS(debug=broken)))
    service=module.ConversionNotificationService(settings=DummySettings({SET_KEY_NOTIFICATIONS_ENABLED:True}),
        emit=broken,log=broken)
    service.on_file_result('video.mkv','❌','failed')


def test_gui_notification_failure_cannot_omit_installed_output():
    from dragontools.gui.conversion_result_file_events import ConversionResultFileEventsMixin
    from dragontools.gui.conversion_session_state import ConversionSessionState
    class Harness(ConversionResultFileEventsMixin): pass
    def broken(*args): raise RuntimeError('notification unavailable')
    harness=Harness();harness._state=ConversionSessionState()
    harness._state.thread=NS()
    harness._notifications=NS(on_file_result=broken)
    harness._log=broken
    for name in ('_set_file_list_item_text','_record_terminal_result','_record_journal_result',
                 '_update_result_sidecars','_update_result_postprocess','_refresh_queue'):
        setattr(harness,name,lambda *args:None)
    harness.on_file_result('source.mkv','installed.mkv','✅')
    assert harness._state.fertig=={'installed.mkv'}
    assert harness._state.artifacts_by_input['source.mkv'].status=='✅'


def test_late_foreign_nfo_backup_is_preserved(tmp_path,monkeypatch):
    from dragontools.worker import nfo_commit as module
    target=tmp_path/'movie.nfo';target.write_bytes(b'OLD')
    backup=target.with_suffix('.nfo.bak')
    original=module.shutil.copystat
    def race(source,destination,**kwargs):
        original(source,destination,**kwargs)
        backup.write_bytes(b'FOREIGN-BACKUP')
    monkeypatch.setattr(module.shutil,'copystat',race)
    with pytest.raises(FileExistsError):
        module.commit_nfo(module.plan_nfo_target(target,'backup'),lambda path:Path(path).write_bytes(b'NEW'))
    assert target.read_bytes()==b'OLD' and backup.read_bytes()==b'FOREIGN-BACKUP'


def test_prepared_nfo_cannot_be_installed_for_another_video(tmp_path):
    from dragontools.worker.postprocess_models import PreparedNfo
    from dragontools.worker.postprocess_runner import PostProcessService
    stage=tmp_path/'.prepared.nfo';stage.write_text('<movie><title>First</title></movie>',encoding='utf-8')
    other=tmp_path/'other.mkv';other.write_bytes(b'OTHER-VIDEO')
    prepared=PreparedNfo(str(stage),str(tmp_path/'first.nfo'),'overwrite','movie',object())
    result=PostProcessService(settings=None,tools=NS(),log=None).commit_prepared_nfo(prepared,final_output_path=str(other))
    assert result.items[0]['status']=='error' and not other.with_suffix('.nfo').exists()


def test_reminder_updates_are_serialized_between_processes(tmp_path):
    import os, subprocess, sys, time
    from dragontools.core.replacement_reminders import list_replacement_reminders
    code = '''
from pathlib import Path
import sys, time
from datetime import datetime
from dragontools.core import replacement_reminders as module
folder=Path(sys.argv[1]);number=sys.argv[2];other='2' if number=='1' else '1'
original=module._load
def synchronized_load(path, **kwargs):
    result=original(path, **kwargs)
    (folder/('read-'+number)).touch()
    deadline=time.monotonic()+.5
    while not (folder/('read-'+other)).exists() and time.monotonic()<deadline:time.sleep(.01)
    return result
module._load=synchronized_load
(folder/('ready-'+number)).touch()
deadline=time.monotonic()+10
while not (folder/'start').exists():
    if time.monotonic()>deadline:raise RuntimeError('start timeout')
    time.sleep(.01)
module.add_replacement_reminder(series_name='series',season=1,episode=int(number),episode_label=number,
    old_paths=['old-'+number],new_path='new-'+number,reason='replace',path=folder/'reminders.json',
    now=datetime(2026,10,6))
'''
    processes=[subprocess.Popen([sys.executable,'-B','-c',code,str(tmp_path),number],
        cwd=Path(__file__).resolve().parents[2],stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        **({'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {})) for number in ('1','2')]
    try:
        deadline=time.monotonic()+10
        while not all((tmp_path/('ready-'+number)).exists() for number in ('1','2')):
            assert time.monotonic()<deadline
            time.sleep(.01)
        (tmp_path/'start').touch()
        for process in processes:
            _,errors=process.communicate(timeout=10)
            assert process.returncode==0,errors
        reminders=list_replacement_reminders(tmp_path/'reminders.json')
        assert len(reminders)==2 and len({item['id'] for item in reminders})==2
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill();process.wait(timeout=5)
