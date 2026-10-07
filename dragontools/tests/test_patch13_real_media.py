"""Inspect actual packets and decoded frame timestamps at the repair boundary."""
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from dragontools.core.resource_paths import known_tool_dirs
from dragontools.tests.ci_requirements import external_media_environment
from dragontools.worker.duration_repair_runtime import DurationRepairRuntime
from dragontools.worker.duration_remux_service import DurationRemuxService
from dragontools.worker.duration_timing_analyzer import MediaTimingAnalyzer
from dragontools.worker.duration_original_timeline_service import OriginalTimelineRepairService
from dragontools.worker.duration_repair_stream_guard import RepairStreamGuard
from dragontools.worker.duration_packet_integrity import PacketIntegrityVerifier
from dragontools.worker.owned_probe import owned_probe_runner
from dragontools.worker.output_verifier import OutputVerifier
from dragontools.worker.tool_runner import run_tool
from dragontools.worker.workflow_engine import WorkflowVerifyResult

pytestmark=pytest.mark.media_integration


def run(command):
    result=subprocess.run(command,capture_output=True,text=True,timeout=90)
    assert result.returncode in (0,1),result.stderr[-3000:]
    return result


@pytest.fixture
def tools():
    env=external_media_environment()
    mkvmerge=os.environ.get('DRAGONTOOLS_MKVMERGE') or shutil.which('mkvmerge')
    if not mkvmerge:
        mkvmerge=next((str(d/'mkvmerge.exe') for d in known_tool_dirs() if (d/'mkvmerge.exe').is_file()),None)
    if not all((env.ffmpeg,env.ffprobe,env.mp4box,mkvmerge)):
        pytest.skip('FFmpeg, ffprobe, MKVToolNix or MP4Box unavailable')
    return NS(ffmpeg=env.ffmpeg,ffprobe=env.ffprobe,mp4box=env.mp4box,mkvmerge=mkvmerge)


def runtime(tools):
    worker=NS(abort_requested=False,abort_type='sofort',paused=False,
        _process_lock=threading.RLock(),_current_process=None)
    return DurationRepairRuntime(tools.mkvmerge,tools.mp4box,tools.ffmpeg,tools.ffprobe,'',
        OutputVerifier(ffprobe_path=tools.ffprobe,worker=worker),lambda *_:None,worker,run_tool)


def create_video(tools,path,*,vfr=False,video_delay=0):
    command=[tools.ffmpeg,'-y','-v','error']
    if video_delay:
        command+=['-itsoffset',str(video_delay)]
    command+=['-f','lavfi','-i','testsrc2=size=160x90:rate=25:duration=2']
    if video_delay:
        command+=['-f','lavfi','-i','sine=frequency=440:duration=2','-c:a','aac']
    if vfr:
        command+=['-vf',r'select=not(eq(mod(n\,4)\,1))','-fps_mode','vfr']
    run(command+['-c:v','libx264','-preset','ultrafast','-bf','0',str(path)])


@pytest.mark.parametrize('container',['mkv','mp4'])
def test_real_normal_remux_requires_and_preserves_packet_payload(tmp_path,tools,container):
    out=tmp_path/f'Quelle ü.{container}';reference=tmp_path/f'Referenz Ω.{container}'
    create_video(tools,out);shutil.copy2(out,reference)
    rt=runtime(tools)
    result=DurationRemuxService(rt).attempt(out=out,container=container,expected_duration_ms=2000,
        source_has_audio=False,initial_result=WorkflowVerifyResult(messages=[]))
    assert result[2],result[3]
    integrity=PacketIntegrityVerifier(ffprobe_path=tools.ffprobe,run_tool=rt.run_tool).validate(
        str(reference),str(out),reference_duration_s=2,frame_rate=None)
    assert integrity.ok and integrity.available,integrity.messages
    assert rt.worker._current_process is None


@pytest.mark.parametrize('video_delay',[0,.8])
def test_real_vfr_repair_restores_every_original_frame_pts(tmp_path,tools,video_delay):
    source=tmp_path/'Original VFR ä.mkv';out=tmp_path/'Beschädigte Timeline ü.mkv'
    create_video(tools,source,vfr=True,video_delay=video_delay);source_bytes=source.read_bytes()
    rt=runtime(tools)
    analyzer=MediaTimingAnalyzer(ffprobe_path=tools.ffprobe,run_command=owned_probe_runner(rt.worker))
    guard=RepairStreamGuard(timing_analyzer=analyzer,ffprobe_path=tools.ffprobe,mediainfo_path='',
        mkvmerge_path=tools.mkvmerge,run_tool_fn=rt.run_tool,log=rt.log)
    service=OriginalTimelineRepairService(rt,analyzer,guard)
    timeline=service._read_source_timeline(source)
    assert len({round(b-a,3) for a,b in zip(timeline.timestamps_s,timeline.timestamps_s[1:])})>1
    broken=tmp_path/'wrong timecodes.txt'
    broken.write_text('# timestamp format v2\n'+'\n'.join(str(i*200) for i in range(timeline.frame_count)),encoding='utf-8')
    run([tools.mkvmerge,'-o',str(out),'--timestamps',f'0:{broken}',str(source)])
    before=analyzer.get_media_timing_info(str(out));before.frame_rate_mode='VFR'
    result=service.try_repair(source=source,out=out,base_dir=tmp_path,container='mkv',
        expected_duration_ms=2000,expected_duration_s=2,source_has_audio=bool(video_delay),
        reference_result=WorkflowVerifyResult(messages=[]),before=before,timing_summary=[])
    assert result.repaired,result.reason
    actual=service._read_source_timeline(out)
    assert actual.timestamps_s==pytest.approx(timeline.timestamps_s,abs=.002)
    assert actual.frame_count==timeline.frame_count
    def starts(path):
        data=json.loads(run([tools.ffprobe,'-v','error','-show_streams','-of','json',str(path)]).stdout)
        return {s['codec_type']:float(s['start_time']) for s in data['streams']}
    original_starts,actual_starts=starts(source),starts(out)
    if video_delay:
        assert original_starts['video']-original_starts['audio']==pytest.approx(video_delay,abs=.03)
        assert actual_starts['video']-actual_starts['audio']==pytest.approx(
            original_starts['video']-original_starts['audio'],abs=.002)
    assert source.read_bytes()==source_bytes
    assert rt.worker._current_process is None


def test_real_malformed_video_is_rejected_by_owned_verifier(tmp_path,tools):
    path=tmp_path/'broken.mkv';path.write_bytes(b'not-media'*2048)
    rt=runtime(tools)
    result=rt.output_verifier.verify(str(path),'mkv')
    assert not result.ok and not result.probe_ok
    assert path.read_bytes()==b'not-media'*2048
    assert rt.worker._current_process is None
