"""Real analysis -> stream policy -> FFmpeg -> semantic output verification."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace as NS

import pytest

from dragontools.core.media_analyzer import analyze_media
from dragontools.worker.converter_audio_args import build_audio_args
from dragontools.worker.converter_subtitle_args import build_subtitle_args
from dragontools.worker.media_contract import build_expected_media_contract
from dragontools.worker.output_verifier import OutputVerifier
from dragontools.worker.workflow_services import WorkflowServices


CASES = [
    ('mkv','mp4','h264',1,'aac','srt'),
    ('mp4','mkv','h264',2,'aac','mov_text'),
    ('mkv','mp4','hevc',6,'eac3','ass'),
    ('mp4','mkv','hevc',1,'eac3','mov_text'),
    ('mkv','mp4','av1',2,'aac','none'),
    ('mp4','mkv','av1',6,'eac3','mov_text'),
]


def run(command):
    result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
        text=True, encoding='utf-8', errors='replace', timeout=60)
    assert result.returncode==0, result.stderr


class Log:
    def __getattr__(self, name): return lambda *args, **kw: None


@pytest.mark.media_integration
@pytest.mark.parametrize('source_ext,output_ext,codec,channels,audio_codec,sub_codec', CASES)
def test_native_contract_chain(source_ext,output_ext,codec,channels,audio_codec,sub_codec,tmp_path):
    ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    if not ffmpeg or not ffprobe: pytest.skip('FFmpeg/ffprobe unavailable')
    source = tmp_path / f'Quelle Ü.{source_ext}'
    output = tmp_path / f'Ausgabe ä.{output_ext}'
    subtitle = tmp_path / 'Deutsch text.srt'
    subtitle.write_text('1\n00:00:00,000 --> 00:00:00,350\nDragonTools\n', encoding='utf-8')
    video = {'h264':['-c:v','libx264','-preset','ultrafast'],
        'hevc':['-c:v','libx265','-preset','ultrafast','-x265-params','pools=1:frame-threads=1'],
        'av1':['-c:v','libaom-av1','-cpu-used','8']}[codec]
    cmd=[ffmpeg,'-v','error','-y','-f','lavfi','-i','color=s=64x64:r=25:d=0.4',
        '-f','lavfi','-i','sine=frequency=750:sample_rate=48000:duration=0.4']
    if sub_codec!='none': cmd += ['-i',str(subtitle)]
    cmd += ['-map','0:v:0','-map','1:a:0']
    if sub_codec!='none': cmd += ['-map','2:s:0','-c:s',sub_codec,'-metadata:s:s:0','language=deu','-disposition:s:0','0']
    cmd += [*video,'-threads','1','-pix_fmt','yuv420p','-c:a',audio_codec,'-ac',str(channels),
        '-metadata:s:a:0','language=deu','-disposition:a:0','default',str(source)]
    run(cmd)
    original_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    tools = NS(ffmpeg=ffmpeg,ffprobe=ffprobe,
        mediainfo=shutil.which('mediainfo') or 'not-installed-mediainfo')
    info=analyze_media(str(source),tools)
    assert info.primary_video.codec==codec
    assert info.audio_streams[0].channels==channels
    override={'audio_mode':'custom','audio_tracks':[{'index':info.audio_streams[0].index,'mode':'auto'}],
        'subtitle_mode':'custom','subtitle_tracks':[{'index':s.index,'keep':True,'burn_in':False} for s in info.subtitle_streams]}
    rules={'mp4_sidecars_enabled':False}
    worker=NS(_logger=Log(),log=lambda *a:None)
    audio_args=build_audio_args(worker,info,override,output_ext)
    burn,sub_args=build_subtitle_args(worker,str(source),info,override,container=output_ext,subtitle_rules=rules)
    assert not burn
    contract=build_expected_media_contract(media_info=info,file_override=override,container=output_ext,
        pipeline='standard',strip_only=True,effective_codec='h265',effective_preserve_hdrplus=False,subtitle_rules=rules)
    run([ffmpeg,'-v','error','-y','-i',str(source),'-map',f'0:{info.primary_video.index}',
        '-c:v','copy',*audio_args,*sub_args,str(output)])
    WorkflowServices._finalize_container_metadata(NS(output_path=str(output), input_path=str(source),
        expected_media_contract=contract))
    result=OutputVerifier(ffprobe_path=ffprobe).verify(str(output),output_ext,
        expected_duration_ms=400,expected_contract=contract)
    assert result.ok,result.messages
    assert result.audio_stream_count==1
    assert result.subtitle_stream_count==int(sub_codec!='none')
    assert hashlib.sha256(source.read_bytes()).hexdigest()==original_hash
