"""Final verification, repair and recovery boundaries beyond argv success."""
import io
import json
import os
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from dragontools.worker.workflow_engine import WorkflowVerifyResult


def accepted():
    return WorkflowVerifyResult(exists=True, size_ok=True, container_ok=True,
        probe_ok=True, video_ok=True, audio_ok=True, subtitle_ok=True,
        contract_ok=True, metadata_ok=True, duration_ok=True, duration_s=10,
        messages=[])


def tool_result(**kwargs):
    return NS(**dict(dict(returncode=0, stdout='', stderr='', aborted=False,
                         timed_out=False), **kwargs))


def worker():
    return NS(abort_requested=False, abort_type='', _control_state=NS(abort_requested=False, abort_type=''))


@pytest.mark.parametrize('kind', ['duration', 'rejected', 'verification', 'size'])
def test_archive_conflict_never_overwrites_foreign_bytes(tmp_path, monkeypatch, kind):
    from dragontools.worker.duration_repair_archive import DurationRepairArchive
    from dragontools.worker.duration_timestamp_candidate_archive import RejectedTimestampArchive
    from dragontools.worker.output_verification_archive import preserve_failed_verification_output
    from dragontools.worker.output_size_policy import _preserve_in_archiv
    source, candidate = tmp_path/'source.mkv', tmp_path/'candidate.mkv'
    source.write_bytes(b'SOURCE')
    candidate.write_bytes(b'CANDIDATE')
    rename, replace = os.rename, os.replace
    occupied = []
    def raced(fn):
        def operation(src, dst, *args, **kwargs):
            target = Path(dst)
            if 'Archiv' in target.parts and not target.name.startswith('.'):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b'FOREIGN')
                occupied.append(target)
            return fn(src, dst, *args, **kwargs)
        return operation
    monkeypatch.setattr(os, 'rename', raced(rename))
    monkeypatch.setattr(os, 'replace', raced(replace))
    runtime = NS(log=lambda *_: None, replace_file=lambda src,dst: os.replace(src,dst),
                 safe_unlink=lambda p: Path(p).unlink(missing_ok=True))
    try:
        if kind == 'duration':
            DurationRepairArchive(runtime).archive(candidate, tmp_path)
        elif kind == 'rejected':
            RejectedTimestampArchive(runtime).archive(candidate, out=source,
                base_dir=tmp_path, label='rejected', reason='bad')
        elif kind == 'verification':
            ctx = NS(input_path=str(source), output_path=str(candidate))
            preserve_failed_verification_output(ctx, accepted(), logger=NS(warn=lambda *_: None))
        else:
            _preserve_in_archiv(input_path=source, output_path=candidate)
    except OSError:
        pass
    assert occupied and all(p.read_bytes() == b'FOREIGN' for p in occupied)
    assert candidate.read_bytes() == b'CANDIDATE'
    assert source.read_bytes() == b'SOURCE'


def test_cross_volume_corrupt_equal_size_copy_keeps_candidate(tmp_path, monkeypatch):
    from dragontools.worker import output_verification_archive as module
    candidate, target = tmp_path/'candidate.mkv', tmp_path/'archive.mkv'
    candidate.write_bytes(b'GOOD' * 100)
    def corrupt(src, dst, **_kwargs):
        Path(dst).write_bytes(b'BAD!' * 100)
    monkeypatch.setattr(module.shutil, 'copy2', corrupt)
    with pytest.raises(OSError):
        module._cross_volume_preserve(candidate, target)
    assert candidate.read_bytes() == b'GOOD' * 100
    assert not target.exists()


def test_archive_logger_failure_does_not_hide_durable_output(tmp_path):
    from dragontools.worker.output_verification_archive import preserve_failed_verification_output
    source, candidate = tmp_path/'source.mkv', tmp_path/'candidate.mkv'
    source.write_bytes(b'SOURCE')
    candidate.write_bytes(b'RECOVERY')
    ctx = NS(input_path=str(source), output_path=str(candidate))
    def broken(*_):
        raise RuntimeError('logger unavailable')
    archived = preserve_failed_verification_output(ctx, accepted(), logger=NS(warn=broken))
    assert archived and Path(archived).read_bytes() == b'RECOVERY'


def test_container_commit_conflict_keeps_source_and_verified_stage(tmp_path, monkeypatch):
    from dragontools.core import output_replace
    source, stage, target = [tmp_path/name for name in ['source.mkv','stage.mp4','source.mp4']]
    source.write_bytes(b'SOURCE'); stage.write_bytes(b'VERIFIED')
    rename, replace = os.rename, os.replace
    def raced(fn):
        def operation(src, dst, *a, **kw):
            if Path(dst) == target:
                target.write_bytes(b'FOREIGN')
            return fn(src, dst, *a, **kw)
        return operation
    monkeypatch.setattr(os, 'rename', raced(rename)); monkeypatch.setattr(os, 'replace', raced(replace))
    with pytest.raises((OSError, RuntimeError)):
        output_replace.commit_staged_output(source=source, staging=stage, destination=target,
            journal_root=tmp_path, log=lambda *_: None)
    assert source.read_bytes() == b'SOURCE' and stage.read_bytes() == b'VERIFIED'
    assert target.read_bytes() == b'FOREIGN'


@pytest.mark.parametrize('flag', ['aborted', 'timed_out', 'negative', 'late_abort'])
def test_remux_never_commits_stopped_result(tmp_path, flag):
    from dragontools.worker.duration_remux_service import DurationRemuxService
    out = tmp_path/'film.mkv'; out.write_bytes(b'ORIGINAL' * 256)
    owned = worker()
    def run(command, **kwargs):
        Path(command[command.index('-o')+1]).write_bytes(b'REMUX' * 512)
        return tool_result(**({flag: True} if flag in {'aborted','timed_out'} else
                             {'returncode': -15} if flag == 'negative' else {}))
    def verify(*a, **kw):
        if flag == 'late_abort': owned._control_state.abort_requested=True; owned._control_state.abort_type='sofort'
        return accepted()
    runtime = NS(worker=owned, mkvmerge_path='mkvmerge', mp4box_path='mp4box',
        run_tool=run, output_verifier=NS(verify=verify), replace_file=lambda a,b: a.replace(b),
        safe_unlink=lambda p: p.unlink(missing_ok=True), log=lambda *_: None)
    service = DurationRemuxService(runtime)
    service._packet_integrity = NS(validate=lambda *a,**kw:NS(ok=True,available=True,messages=[]))
    result = service.attempt(out=out, container='mkv',
        expected_duration_ms=10000, source_has_audio=False, initial_result=accepted())
    assert not result[2] and out.read_bytes() == b'ORIGINAL' * 256


@pytest.mark.parametrize('flag', ['aborted', 'timed_out', 'late_abort'])
def test_timestamp_candidate_never_commits_after_stop(tmp_path, flag):
    from dragontools.worker.duration_timestamp_candidate_service import TimestampCandidateService
    out, stage = tmp_path/'film.mkv', tmp_path/'candidate.mkv'
    out.write_bytes(b'ORIGINAL'*256); stage.write_bytes(b'REPAIRED'*256)
    owned=worker()
    runtime=NS(worker=owned, ffprobe_path='', log=lambda *_: None,
        run_tool=lambda *a,**kw: tool_result(**({flag:True} if flag!='late_abort' else {})),
        replace_file=lambda a,b: a.replace(b), safe_unlink=lambda p: p.unlink(missing_ok=True))
    service=TimestampCandidateService(runtime, NS(), NS())
    def validate(*a,**kw):
        if flag=='late_abort': owned._control_state.abort_requested=True; owned._control_state.abort_type='sofort'
        return NS(ok=True, repaired_info=NS(container_duration_s=10), verify_result=accepted(), messages=[])
    service._validator=NS(validate=validate)
    service._archive=NS(archive=lambda *a,**kw: None)
    result=service.attempt(out=out,tmp=stage,command=[],label='repair',method='FFmpeg setts',
        container='mkv',before=NS(),before_ffprobe=None,before_mediainfo=None,timing_summary=[])
    assert not result.repaired and out.read_bytes()==b'ORIGINAL'*256


@pytest.mark.parametrize('parser,value', [('parse_seconds','nan'),('parse_seconds','inf'),
    ('parse_int','inf'),('parse_int','12.5'),('parse_int',True),
    ('parse_duration_tag','00:61:00'),('parse_duration_tag','-1:00:00')])
def test_invalid_timing_is_unknown_instead_of_authoritative(parser,value):
    from dragontools.worker import duration_timing_parsing as parsing
    assert getattr(parsing,parser)(value) is None


def test_timing_analysis_selects_program_video_after_cover():
    from dragontools.worker.duration_timing_mapping import apply_ffprobe_timing
    from dragontools.worker.duration_repair_models import MediaTimingInfo
    info=MediaTimingInfo('file.mp4')
    apply_ffprobe_timing(info, {'streams':[
        {'index':0,'codec_type':'video','codec_name':'mjpeg','nb_frames':'1','duration':'1',
         'disposition':{'attached_pic':1}},
        {'index':1,'codec_type':'video','codec_name':'h264','nb_frames':'250','duration':'10',
         'avg_frame_rate':'25/1','r_frame_rate':'25/1'}]})
    assert info.codec=='h264' and info.video_stream_count==1 and info.video_frame_count==250
    assert info.video_duration_s==10 and info.attachment_stream_count==1


def test_timing_duration_tag_is_endpoint_relative_to_start():
    from dragontools.worker.duration_timing_parsing import stream_duration
    assert stream_duration({'start_time':'2.0','tags':{'DURATION':'00:00:12.000'}})==10


def test_nan_source_reference_does_not_mask_valid_video_reference():
    from dragontools.worker.duration_repair_models import MediaTimingInfo
    from dragontools.worker.duration_repair_validation import source_video_reference_s
    source=MediaTimingInfo('source',video_duration_s=float('nan'),container_duration_s=10)
    assert source_video_reference_s(source)==10


def test_known_vfr_is_not_converted_to_cfr_by_average_frame_count():
    from dragontools.worker.duration_repair_models import MediaTimingInfo, detect_timestamp_problem
    from dragontools.worker.duration_timing_inference import derive_frame_rate_from_source_duration
    info=MediaTimingInfo('vfr.mkv',video_frame_count=25000,frame_rate=Fraction(25),
        frame_rate_mode='VFR',container_duration_s=4295967.296,video_duration_s=4295967.296,
        audio_duration_s=1000)
    derive_frame_rate_from_source_duration(info,1000)
    assert info.frame_rate_mode=='VFR' and not detect_timestamp_problem(info,expected_duration_s=1000).should_repair


@pytest.mark.parametrize('flag', ['aborted','timed_out'])
def test_packet_probe_stop_is_not_hash_evidence(monkeypatch,flag):
    from dragontools.worker import duration_packet_integrity as module
    monkeypatch.setattr(module,'tool_available',lambda *_:True)
    payload={'streams':[{'index':0,'codec_type':'video'}], 'packets':[
        {'stream_index':0,'data_hash':'SHA256:abc','pts_time':'0','duration_time':'0.04'}]}
    verifier=module.PacketIntegrityVerifier(ffprobe_path='ffprobe',run_tool=lambda *a,**kw:
        tool_result(stdout=json.dumps(payload),**{flag:True}))
    result=verifier.validate('before','after',reference_duration_s=10,frame_rate=Fraction(25))
    assert not result.ok and not result.available


@pytest.mark.parametrize('field,value',[('pts_time','nan'),('pts_time',None),
    ('dts_time','inf'),('duration_time','nan'),('duration_time','-1')])
def test_packet_timeline_requires_finite_evidence(field,value):
    from dragontools.worker.packet_snapshot import read_snapshot
    record={'stream_index':0,'data_hash':'SHA256:abc','pts_time':'0','dts_time':'0','duration_time':'0.04'}
    if value is None: record.pop(field)
    else: record[field]=value
    payload={'streams':[{'index':0,'codec_type':'video'}],'packets':[record]}
    with pytest.raises(ValueError): read_snapshot(io.StringIO(json.dumps(payload)))


def test_frame_evidence_invalidated_by_same_size_same_mtime_replacement(tmp_path):
    from dragontools.worker.frame_count_evidence import FrameCountEvidence
    path=tmp_path/'video.hevc'; path.write_bytes(b'AAAA')
    evidence=FrameCountEvidence.reliable(10,source='counted',path=path,stage='encode')
    original=path.stat()
    backup=path.with_suffix('.old'); path.rename(backup)
    path.write_bytes(b'BBBB'); os.utime(path,ns=(original.st_atime_ns,original.st_mtime_ns))
    assert not evidence.is_reliable_for(path)


@pytest.mark.parametrize('chain',['fps@cadence=50','setpts@clock=PTS*2','tmix=frames=3','shuffleframes=1 0',
                                'select@drop=not(mod(n,2))'])
def test_named_or_temporal_filters_cannot_claim_preserved_mapping(chain):
    from dragontools.worker.frame_count_evidence import temporal_mapping_for_filters
    assert temporal_mapping_for_filters(['-vf',chain])!='preserved'


@pytest.mark.parametrize('flag',['aborted','timed_out'])
def test_output_probe_rejects_stopped_semantic_payload(tmp_path,flag):
    from dragontools.worker.output_probe import probe_output
    payload={'format':{'format_name':'matroska','duration':'10'},'streams':[{'codec_type':'video','codec_name':'h264'}]}
    with pytest.raises((RuntimeError,ValueError)):
        probe_output(tmp_path/'file.mkv',ffprobe_path='ffprobe',run_process=lambda *a,**kw:
            tool_result(stdout=json.dumps(payload),**{flag:True}),no_window_kwargs={})


def test_vfr_candidate_payload_change_is_rejected(tmp_path,monkeypatch):
    from dragontools.worker.duration_original_timeline_service import OriginalTimelineRepairService,SourceVideoTimeline
    from dragontools.worker.duration_repair_models import MediaTimingInfo
    out,stage=tmp_path/'before.mkv',tmp_path/'candidate.mkv'
    out.write_bytes(b'BEFORE');stage.write_bytes(b'CHANGED')
    timing=MediaTimingInfo(str(stage),video_frame_count=2,video_duration_s=2,
        container_duration_s=2,frame_rate=Fraction(1),video_stream_count=1)
    def run(command,**kw):
        if '-show_packets' in command:
            payload={'streams':[{'index':0,'codec_type':'video'}],'packets':[
                {'stream_index':0,'pts_time':'0','duration_time':'1','data_hash':
                 'SHA256:before' if str(command[-1])==str(out) else 'SHA256:changed'}]}
        else: payload={'frames':[{'pts_time':'0','pkt_duration_time':'1'},{'pts_time':'1','pkt_duration_time':'1'}]}
        return tool_result(stdout=json.dumps(payload))
    runtime=NS(ffprobe_path='ffprobe',run_tool=run,log=lambda *_:None,
               output_verifier=NS(verify=lambda *a,**kw:accepted()))
    monkeypatch.setattr('dragontools.worker.duration_packet_integrity.tool_available',lambda *_:True)
    guard=NS(validate=lambda **kw:NS(ok=True,messages=[],confirmed_kinds={'video'}))
    service=OriginalTimelineRepairService(runtime,NS(get_media_timing_info=lambda *a,**kw:timing),guard)
    before=MediaTimingInfo(str(out),video_frame_count=2,video_stream_count=1)
    reason,_,_=service._validate_candidate(stage,timeline=SourceVideoTimeline((0,1),2),before=before,
        before_ffprobe=None,before_mediainfo=None,container='mkv',expected_duration_ms=2000,
        source_has_audio=False,expected_contract=None,verified_hdr10plus=False,verified_dolby_vision=False)
    assert reason is not None


@pytest.mark.parametrize('available,ok',[(False,False),(True,False)])
def test_normal_remux_requires_lossless_packet_evidence(tmp_path,available,ok):
    from dragontools.worker.duration_remux_service import DurationRemuxService
    out=tmp_path/'film.mkv';out.write_bytes(b'ORIGINAL'*256)
    def run(command,**kw):
        Path(command[command.index('-o')+1]).write_bytes(b'REMUX'*512)
        return tool_result()
    runtime=NS(mkvmerge_path='mkvmerge',mp4box_path='mp4box',run_tool=run,
        output_verifier=NS(verify=lambda *a,**kw:accepted()),log=lambda *_:None,
        replace_file=lambda a,b:a.replace(b),safe_unlink=lambda p:p.unlink(missing_ok=True))
    service=DurationRemuxService(runtime)
    service._packet_integrity=NS(validate=lambda *a,**kw:NS(ok=ok,available=available,messages=['packet evidence missing']))
    result=service.attempt(out=out,container='mkv',expected_duration_ms=10000,
        source_has_audio=False,initial_result=accepted())
    assert not result[2] and out.read_bytes()==b'ORIGINAL'*256


def test_output_verification_probe_is_owned_by_current_worker(tmp_path,monkeypatch):
    from dragontools.worker.output_verifier import OutputVerifier
    from dragontools.worker import owned_probe
    out=tmp_path/'film.mkv';out.write_bytes(b'VIDEO'*512)
    calls=[];owned=worker()
    payload={'format':{'format_name':'matroska','duration':'10'},'streams':[
        {'index':0,'codec_type':'video','codec_name':'h264'}]}
    def run(command,**kwargs):
        calls.append(kwargs)
        return tool_result(stdout=json.dumps(payload))
    monkeypatch.setattr(owned_probe,'run_tool',run)
    result=OutputVerifier(ffprobe_path='ffprobe',worker=owned).verify(str(out),'mkv',expected_duration_ms=10000)
    assert result.ok and calls and calls[0]['worker'] is owned


def test_verification_rejects_stop_after_probe_before_contract(tmp_path,monkeypatch):
    from dragontools.worker.output_verifier import OutputVerifier
    from dragontools.worker import owned_probe
    out=tmp_path/'film.mkv';out.write_bytes(b'VIDEO'*512)
    owned=worker()
    def run(*a,**kw):
        owned._control_state.abort_requested=True;owned._control_state.abort_type='sofort'
        return tool_result(stdout=json.dumps({'format':{'format_name':'matroska','duration':'10'},
            'streams':[{'codec_type':'video','codec_name':'h264'}]}))
    monkeypatch.setattr(owned_probe,'run_tool',run)
    assert not OutputVerifier(ffprobe_path='ffprobe',worker=owned).verify(str(out),'mkv').ok


def test_validation_archive_cannot_move_the_media_source(tmp_path):
    from dragontools.worker.output_verification_archive import preserve_failed_verification_output
    source=tmp_path/'source.mkv';source.write_bytes(b'SOURCE')
    ctx=NS(input_path=str(source),output_path=str(source))
    assert preserve_failed_verification_output(ctx,accepted(),logger=NS(warn=lambda *_:None)) is None
    assert source.read_bytes()==b'SOURCE'


@pytest.mark.parametrize('track_id',[True,-1,1.5,'1.5'])
@pytest.mark.parametrize('original_timeline',[False,True])
def test_timestamp_track_identifier_is_not_rounded(track_id,original_timeline):
    from dragontools.worker.duration_timestamp_helpers import mkv_video_track_id
    from dragontools.worker.duration_original_timeline_service import OriginalTimelineRepairService
    runtime=NS(mkvmerge_path='mkvmerge',run_tool=lambda *a,**kw:tool_result(
        stdout=json.dumps({'tracks':[{'type':'video','id':track_id}]})))
    with pytest.raises((ValueError,TypeError)):
        if original_timeline:
            service=object.__new__(OriginalTimelineRepairService);service._runtime=runtime
            service._mkv_video_track_id(Path('candidate.mkv'))
        else:
            mkv_video_track_id(runtime,Path('candidate.mkv'))


def test_duration_runtime_does_not_start_tool_after_worker_stop():
    from dragontools.worker.duration_repair_runtime import DurationRepairRuntime
    owned=worker();owned._control_state.abort_requested=True;owned._control_state.abort_type='sofort'
    calls=[]
    runtime=DurationRepairRuntime('','','','','',None,lambda *_:None,owned,
        lambda *a,**kw:calls.append(a))
    with pytest.raises(RuntimeError):
        runtime.run_tool(['ffprobe'],label='stopped probe')
    assert not calls


def test_packet_integrity_rejects_wrapped_decode_timestamp(monkeypatch):
    from dragontools.worker.duration_packet_integrity import PacketIntegrityVerifier
    from dragontools.worker.packet_snapshot import PacketStreamSnapshot
    monkeypatch.setattr('dragontools.worker.duration_packet_integrity.tool_available',lambda *_:True)
    verifier=PacketIntegrityVerifier(ffprobe_path='ffprobe',run_tool=None)
    verifier._snapshot=lambda _: (PacketStreamSnapshot(0,'video',0,1,'same',0,4294967,.04),)
    result=verifier.validate('before','after',reference_duration_s=1,frame_rate=Fraction(25))
    assert not result.ok and any('DTS' in m for m in result.messages)
