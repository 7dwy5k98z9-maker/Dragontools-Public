"""Historical 1-video/11-audio/18-subtitle source through actual mux tools."""
from pathlib import Path
from types import SimpleNamespace as NS
import hashlib,json,subprocess
from copy import deepcopy
import io, sqlite3
import pytest
from dragontools.tests.test_patch12_real_media import tools,pgs_fixture,run,probe
from dragontools.core.media_analyzer import analyze_media
from dragontools.worker.dv_mkv_muxer import DVMKVMuxer
from dragontools.worker.dv_audio_mux_service import DVMuxAudioTrack
from dragontools.worker.dv_subtitle_mux_service import DVMuxSubtitleTrack
from dragontools.worker.hdrplus_mux_service import HDRPlusMuxService
from dragontools.worker.dv_remux_muxers import DVRemuxMuxer
from dragontools.worker.media_contract_types import ExpectedMediaContract,ExpectedAudioTrack,ExpectedSubtitleTrack
from dragontools.worker.output_verifier import OutputVerifier
from dragontools.core.move_file_service import MoveFileService

pytestmark=pytest.mark.media_integration

def source_many_tracks(root,tools,qapp):
    text=root/'Text.srt';text.write_text('1\n00:00:00,500 --> 00:00:02,000\nHallo Welt\n',encoding='utf-8')
    pgs=pgs_fixture(root/'Deutsch.sup',qapp)
    base=root/'base.mkv';source=root/'Original Ü.mkv'
    cmd=[tools.ffmpeg,'-v','error','-y','-f','lavfi','-i','color=s=1280x720:r=24:d=3',
        '-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-i',str(text),'-map','0:v:0']
    for _ in range(11):cmd+=['-map','1:a:0']
    for _ in range(17):cmd+=['-map','2:s:0']
    cmd+=['-c:v','libx265','-preset','ultrafast','-x265-params','pools=1:frame-threads=1:log-level=error',
        '-pix_fmt','yuv420p10le','-color_trc','smpte2084','-color_primaries','bt2020','-colorspace','bt2020nc',
        '-c:a','aac','-c:s','srt','-metadata:s:a','language=deu','-metadata:s:s','language=deu',
        '-t','3',str(base)]
    run(cmd)
    run([tools.mkvmerge,'-o',str(source),str(base),'--language','0:deu',
         '--forced-display-flag','0:yes','--default-track-flag','0:yes',str(pgs)])
    rows=probe(source,tools)['streams']
    assert [sum(s['codec_type']==kind for s in rows) for kind in ('video','audio','subtitle')]==[1,11,18]
    pgs_track=next(s for s in rows if s['codec_name']=='hdmv_pgs_subtitle')
    return source,pgs_track

def callback(cmd,**kwargs):
    p=run(cmd)
    return p if kwargs.get('return_process') else p.returncode

@pytest.mark.parametrize('mode',['standard','dv','hdrplus','remux','ocr_success','ocr_failed','sidecar','mp4box','remux_mp4box'])
def test_historical_original_track_explosion_is_excluded(tmp_path,tools,qapp,mode):
    if not tools.mkvmerge:pytest.skip('mkvmerge unavailable')
    source,pgs=source_many_tracks(tmp_path,tools,qapp)
    if mode in {'ocr_failed','mp4box','remux_mp4box'}:
        from dragontools.tests.ci_requirements import external_media_environment
        from dragontools.tests.test_real_dv_hdr_integration import _DOVI_GENERATOR_CONFIG
        from dragontools.worker.dv_source_rpu_check import SourceRpuSanityCheck
        from dragontools.worker.dv_dynamic_metadata_service import DVDynamicMetadataService
        from dragontools.worker.dv_runtime_models import DVTempState
        env=external_media_environment()
        if not env.dovi_tool:pytest.skip('DV tool unavailable')
        base=tmp_path/'source-video.hevc';rpu=tmp_path/'valid.rpu';dv=tmp_path/'valid-dv.hevc';cfg=tmp_path/'dv.json'
        run([tools.ffmpeg,'-v','error','-y','-i',str(source),'-map','0:v:0','-an','-sn','-c:v','copy','-bsf:v','hevc_mp4toannexb',str(base)])
        cfg.write_text(json.dumps(dict(_DOVI_GENERATOR_CONFIG,length=72)),encoding='utf-8')
        run([env.dovi_tool,'generate','-j',str(cfg),'-o',str(rpu)])
        run([env.dovi_tool,'inject-rpu','-i',str(base),'--rpu-in',str(rpu),'-o',str(dv)])
        combined=tmp_path/'Valid DV Original.mkv'
        run([tools.mkvmerge,'-o',str(combined),str(dv),'--no-video',str(source)])
        source=combined
        dynamic=DVDynamicMetadataService.__new__(DVDynamicMetadataService);dynamic._tools=NS(dovi_tool=env.dovi_tool)
        state=NS(request=NS(input_path=str(source),media_info=NS(primary_video=NS(index=0))),files=NS(rpu_orig=rpu))
        assert SourceRpuSanityCheck(tools=tools,temp_state=DVTempState(),log=lambda *a:None).validate(
            state,NS(run=lambda cmd,**kw:run(cmd)),probe_rpu=dynamic.probe_rpu_frame_count)
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    video=tmp_path/'processed.hevc';audio=tmp_path/'selected.eac3'
    run([tools.ffmpeg,'-v','error','-y','-i',str(source),'-map','0:v:0','-an','-sn','-c:v','copy',
         '-bsf:v','hevc_mp4toannexb',str(video)])
    run([tools.ffmpeg,'-v','error','-y','-i',str(source),'-map','0:a:3','-vn','-sn','-c:a','eac3','-ac','2',str(audio)])
    if mode=='hdrplus':
        from dragontools.tests.test_real_dv_hdr_integration import _HDR10PLUS_SINGLE_FRAME
        from dragontools.tests.ci_requirements import external_media_environment
        from dragontools.tests.test_dv_corrupt_rpu_fallback import _ctx,_services
        from dragontools.worker.workflow_models import PipelineExecutionResult
        env=external_media_environment()
        if not env.hdr10plus_tool:pytest.skip('HDR10+ tool unavailable')
        fixture=deepcopy(_HDR10PLUS_SINGLE_FRAME)
        fixture['SceneInfo']=[dict(deepcopy(fixture['SceneInfo'][0]),SceneFrameIndex=i,SequenceFrameIndex=i) for i in range(72)]
        fixture['SceneInfoSummary']['SceneFrameNumbers']=[72]
        metadata=tmp_path/'hdr.json';metadata.write_text(json.dumps(fixture),encoding='utf-8')
        hdr=tmp_path/'hdr.hevc';run([env.hdr10plus_tool,'inject','-i',str(video),'-j',str(metadata),'-o',str(hdr)])
        video=hdr
        failure=PipelineExecutionResult(False,failure_stage='DV SOURCE-RPU-CHECK',failure_reason='SOURCE_RPU_UNUSABLE: 155504/20')
        service,_,_,planning,executor=_services(failure,PipelineExecutionResult.succeeded())
        service.process(_ctx(has_hdrplus=True,preserve_hdrplus=True),{'subtitle_tracks':[{'index':pgs['index'],'keep':True}]})
        assert [r.pipeline for r in executor.requests]==['dv','hdrplus']
        assert executor.requests[-1].preserve_hdrplus and executor.requests[-1].override['preserve_dv'] is False
    output=tmp_path/'Star Wars Episode I - Die dunkle Bedrohung (1999).mkv'
    if mode in {'mp4box','remux_mp4box'}:output=output.with_suffix('.mp4')
    subtitle=DVMuxSubtitleTrack(source,pgs['index'],'hdmv_pgs_subtitle','deu','Deutsch',True,source_direct=True,default=True)
    subtitle_codec='hdmv_pgs_subtitle'
    settings=NS(value=lambda key,default=None,**kw:default)
    messages=[]
    worker=NS(tools=tools,settings=settings,abort_requested=False,abort_type=None,log=lambda *a:messages.append(a))
    if mode in {'ocr_success','ocr_failed','mp4box','remux_mp4box'}:
        from dragontools.worker.bitmap_subtitle_ocr_service import BitmapSubtitleOcrService
        from dragontools.core.media_library_fix_queue import MediaLibraryFixIssue
        issue=MediaLibraryFixIssue(media_id=0,path=str(source),title='PGS',item_type='video',issue_type='ocr',
            action='ocr_bitmap_subtitle',problem='OCR',action_label='OCR',stream_index=pgs['index'],stream_ordinal=18,
            codec='hdmv_pgs_subtitle',language='de')
        if mode in {'ocr_success','mp4box','remux_mp4box'}:
            if not tools.tesseract or not tools.mkvextract:pytest.skip('OCR tools unavailable')
            text=BitmapSubtitleOcrService(settings=settings,tools=tools,worker=worker).create_srt(issue,tmp_path/'OCR.srt')
            assert 'Hallo Welt' in text.read_text(encoding='utf-8')
            subtitle=DVMuxSubtitleTrack(text,0,'srt','deu','Deutsch',True,default=True)
            subtitle_codec='mov_text' if mode in {'mp4box','remux_mp4box'} else 'subrip'
        else:
            bad_tools=NS(**vars(tools));bad_tools.tesseract=str(tmp_path/'absent-tesseract.exe')
            with pytest.raises((RuntimeError,OSError)):
                BitmapSubtitleOcrService(settings=settings,tools=bad_tools,worker=worker).create_srt(issue,tmp_path/'Bad OCR.srt')
            assert source.exists() and video.exists() and not (tmp_path/'Bad OCR.srt').exists()
            # Recovery uses the original PGS with explicit subtitle-only selection.
    if mode=='sidecar':
        from dragontools.worker.subtitle_sidecar_service import SubtitleSidecarService
        media=analyze_media(str(source),tools)
        result=SubtitleSidecarService(ffmpeg_path=tools.ffmpeg,subtitle_rules={},worker=worker,log=lambda *a:None).export_sidecars_result(
            input_path=str(source),output_base=tmp_path/'External',media_info=media,
            file_override={'subtitle_mode':'custom','subtitle_tracks':[{'index':pgs['index'],'keep':True}]},container='mp4')
        assert result.complete and len(result.exported_paths)==1
        assert Path(result.exported_paths[0]).suffix=='.sup'
        subtitles=[]
    else:subtitles=[subtitle]
    muxer=DVMKVMuxer(mkvmerge_path=tools.mkvmerge,ffprobe_path=tools.ffprobe,audio_track_name=lambda m:'Deutsch EAC3',log=lambda *a:messages.append(a))
    tracks=[DVMuxAudioTrack(0,audio,{'lang':'deu','default':True,'forced':False})]
    if mode in {'mp4box','remux_mp4box'}:
        worker.tools.mp4box=env.mp4box
        if mode=='mp4box':
            from dragontools.worker.dv_mp4box_muxer import DVMP4BoxMuxer
            assert DVMP4BoxMuxer(mp4box_path=env.mp4box,audio_track_name=lambda m:'Deutsch EAC3').mux_final_output(
                callback,output_path=str(output),injected_hevc=video,mux_tracks=tracks,subtitle_tracks=subtitles)
        else:
            class Runner:
                def run_abortable_capture(self,cmd,**kw):
                    p=run(cmd);return p.returncode,p.stdout,p.stderr
            assert DVRemuxMuxer(worker,Runner()).mux_mp4(str(video),[(str(audio),{'language':'deu','default':True})],str(output),subtitle_tracks=subtitles)
    elif mode=='remux':
        class Runner:
            def run_abortable_capture(self,cmd,**kw):
                p=run(cmd);return p.returncode,p.stdout,p.stderr
        assert DVRemuxMuxer(worker,Runner()).mux_mkv(str(video),[(str(audio),{'language':'deu','title':'Deutsch EAC3','default':True,'forced':False})],str(output),subtitle_tracks=subtitles)
    elif mode=='hdrplus':
        donor=tmp_path/'planned-donor.mkv'
        assert muxer.mux_final_output(callback,output_path=str(donor),injected_hevc=video,mux_tracks=tracks,subtitle_tracks=subtitles)
        def capture(cmd,**kw):
            p=run(cmd);return NS(ok=True,stdout=p.stdout,stderr=p.stderr)
        service=HDRPlusMuxService(tools=tools,log=lambda *a:None,run_mux_tool=lambda cmd,**kw:run(cmd).returncode in (0,1),capture_tool=capture)
        assert service.mux_mkv(str(video),str(donor),str(output))
    elif mode=='standard':
        # Real selected-stream encode/mux: no implicit full-container mapping.
        run([tools.ffmpeg,'-v','error','-y','-i',str(source),'-map','0:v:0','-map','0:a:3','-map',f"0:{pgs['index']}",
            '-c:v','copy','-c:a','eac3','-c:s','copy','-metadata:s:a:0','language=deu',
            '-metadata:s:s:0','language=deu','-disposition:a:0','default','-disposition:s:0','default+forced',str(output)])
    else:
        assert muxer.mux_final_output(callback,output_path=str(output),injected_hevc=video,mux_tracks=tracks,subtitle_tracks=subtitles),messages
    container='mp4' if mode in {'mp4box','remux_mp4box'} else 'mkv'
    contract=ExpectedMediaContract(container=container,video_codec='hevc',video_stream_count=1,
        audio_tracks=(ExpectedAudioTrack('eac3',2,'deu',True,forced=False),),
        subtitle_tracks=() if mode=='sidecar' else (ExpectedSubtitleTrack(subtitle_codec,'deu',True,True),),require_hdr10plus=mode=='hdrplus')
    verified_hdr=False
    if mode=='hdrplus':
        from dragontools.worker.hdr10plus_bitstream_service import HDR10PlusBitstreamService
        final_raw=tmp_path/'final.hevc'
        run([tools.ffmpeg,'-v','error','-y','-i',str(output),'-map','0:v:0','-an','-sn','-c:v','copy','-bsf:v','hevc_mp4toannexb',str(final_raw)])
        bitstream=HDR10PlusBitstreamService(hdr10plus_tool_path=env.hdr10plus_tool,log=lambda *a:None)
        verified_hdr=bitstream.verify_metadata(lambda cmd,**kw:run(cmd).returncode,source_stream=final_raw,
            scratch_json=tmp_path/'verified.json',expected_json=metadata)
        assert verified_hdr
    result=OutputVerifier(ffprobe_path=tools.ffprobe).verify(str(output),container,expected_contract=contract,expected_duration_ms=3000,verified_hdr10plus=verified_hdr)
    assert result.ok,result.messages
    rows=probe(output,tools)['streams']
    assert [sum(s['codec_type']==kind for s in rows) for kind in ('video','audio','subtitle')]==[1,1,0 if mode=='sidecar' else 1]
    library=tmp_path/'library';library.mkdir()
    old=library/'Star Wars Episode I – Die dunkle Bedrohung (1999).mkv';old.write_bytes(b'old-good')
    if mode=='ocr_failed':
        # An intentionally corrupted post-mux contract blocks replacement.
        rejected=OutputVerifier(ffprobe_path=tools.ffprobe).verify(str(source),'mkv',expected_contract=contract)
        assert not rejected.ok and any('Anzahl' in m for m in rejected.messages)
        assert old.read_bytes()==b'old-good' and source.exists() and video.exists()
    else:
        move=MoveFileService(conflict_mode='overwrite',log=lambda *a:None,wait=lambda:None,abort_immediately=lambda:False)
        ok,details=move.move(output,library)
        assert ok,details
        assert list(library.glob('*.mkv'))+list(library.glob('*.mp4'))==[library/output.name]
        if mode=='hdrplus':
            from dragontools.core.jellyfin_nfo import write_movie_nfo
            from dragontools.core.online_metadata import MovieMetadataSuggestion
            from dragontools.core.media_library_repository_moves import record_moved_file
            from dragontools.core.jellyfin_api import JellyfinClient
            final=library/output.name
            suggestion=MovieMetadataSuggestion('Star Wars',1999,1893,'Star Wars Episode I - Die dunkle Bedrohung','',1999)
            write_movie_nfo(final.with_suffix('.nfo'),suggestion,video_path=final,ffprobe_path=tools.ffprobe)
            db=tmp_path/'library.sqlite'
            record_moved_file(db,output,final,tools=tools,replaced_paths=[old])
            with sqlite3.connect(db) as conn:
                assert conn.execute('SELECT count(*) FROM media_items WHERE active=1 AND exists_flag=1').fetchone()[0]==1
            requests=[]
            def opener(request,**kw):
                assert final.exists() and final.with_suffix('.nfo').exists()
                requests.append(request);return io.BytesIO(b'')
            JellyfinClient('http://synthetic.invalid','synthetic-token',opener=opener).refresh_library()
            assert len(requests)==1 and requests[0].get_method()=='POST'
    assert hashlib.sha256(source.read_bytes()).hexdigest()==digest
