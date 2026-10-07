"""Real pipe/codec/probe/mux tests; the neural model is deliberately not simulated as HDR quality evidence."""
import json
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pytest

from dragontools.tests.ci_requirements import external_media_environment
from dragontools.tests.test_real_dv_hdr_integration import _run
from dragontools.tests.test_patch10_second_review import bridge
from dragontools.worker import comfyui_video_worker as service_module
from dragontools.worker.comfyui_client import ComfyUIResult
from dragontools.worker.standard_pipeline_runner import StandardPipelineRunner
from dragontools.worker.workflow_models import PipelineExecutionRequest
from dragontools.core.models import MediaInfo, VideoStream

pytestmark = pytest.mark.dv_hdr_integration


def probe(tools, path):
    return json.loads(_run([tools.ffprobe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)]).stdout)


class NumpyTensor:
    def __init__(self, data): self.data = data
    def float(self):
        self.data = self.data.astype(np.float32)
        return self
    def div_(self, value):
        self.data /= value
        return self
    @property
    def shape(self): return self.data.shape
    def numpy(self): return self.data


@pytest.mark.parametrize('container', ['mkv', 'mp4'])
@pytest.mark.parametrize('delayed', ['audio', 'video'])
@pytest.mark.parametrize('origin', ['zero', 'negative'])
def test_real_bridge_service_mux_preserves_frame_count_hdr_tags_and_av_offset(tmp_path, monkeypatch, container, delayed, origin):
    env = external_media_environment()
    assert env.ffmpeg and env.ffprobe
    tools = NS(ffmpeg=env.ffmpeg, ffprobe=env.ffprobe)
    source = tmp_path / 'SDR Quelle ä.mp4'
    prefix = [env.ffmpeg, '-y', '-loglevel', 'error']
    if delayed == 'video': prefix += ['-itsoffset', '0.4']
    prefix += ['-f', 'lavfi', '-i', 'testsrc2=size=128x72:rate=25:duration=1']
    if delayed == 'audio': prefix += ['-itsoffset', '0.4']
    _run(prefix + ['-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=1',
        '-c:v', 'libx264', '-preset', 'fast', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709',
        '-c:a', 'aac', str(source)])
    if origin == 'negative':
        transport = tmp_path / 'SDR negative Quelle ä.ts'
        _run([env.ffmpeg,'-y','-v','error','-copyts','-i',str(source),'-map','0','-c','copy',
            '-muxpreload','0','-muxdelay','0','-avoid_negative_ts','disabled','-output_ts_offset','-2',str(transport)])
        source = transport
        assert float(probe(tools, source)['format']['start_time']) < 0
    video = VideoStream(index=0, codec='h264', width=128, height=72, color_space='bt709', color_transfer='bt709',
        color_primaries='bt709', frame_rate='25', frame_rate_mode='CFR', frame_count=25)
    media = MediaInfo(path=str(source), video_streams=[video], audio_streams=[], subtitle_streams=[])
    node = bridge(monkeypatch)
    # Identity pixel transform replaces inference only. Real FFmpeg decoder,
    # queue/pipe adapters, encoder, service probe and final mux run unchanged.
    node.torch.from_numpy = NumpyTensor
    monkeypatch.setattr(node, '_convert_batch', lambda _model, images: images)
    workflows = []
    class Client:
        def __init__(self, *_a, **_kw): pass
        def queue_workflow(self, workflow):
            workflows.append(workflow)
            inp = workflow['2']['inputs']
            node.DragonHDRTVDMVideoConvert().convert_video({'device':NS(type='cpu')}, inp['input_video'], inp['output_video'],
                inp['ffmpeg_path'], inp['decode_args_json'], inp['encode_args_json'], inp['hdr_args_json'],
                inp['fps_num'], inp['fps_den'], inp['batch_size'], inp['expected_frames'], inp['manifest_path'])
            return ComfyUIResult(True, prompt_id='actual-pipe-job')
        def history(self, job): return ComfyUIResult(True, payload={job:{'status':{'completed':True,'status_str':'success'}}})
        def cancel(self, job): return ComfyUIResult(True, prompt_id=job)
    monkeypatch.setattr(service_module, 'ComfyUIClient', Client)
    output = tmp_path / ('HDR Ausgabe ä.' + container)
    commands = []
    def progress(cmd, *_):
        commands.append(cmd)
        return _run(cmd).returncode
    request = PipelineExecutionRequest('standard', str(source), str(output), container, media,
        NS(vf_args=['-map','0:v:0'], audio_args=['-map','0:a:0','-c:a','copy'], sn=['-sn'], audio_input_args=[]),
        {}, False, 1400, 'h265', 28, 'ultrafast', {'encoder':'cpu','_sdr_hdr_applied':True,'sdr_hdr_backend':'comfyui'})
    result = StandardPipelineRunner(tools=tools, codec='h265', crf=28, preset='ultrafast', encoder_options={}, progress_runner=progress).execute(request)
    assert result.success, (result.failure_reason, result.tool_output)
    assert len(workflows) == 1 and len(commands) == 1
    before, after = probe(tools, source), probe(tools, output)
    def offset(payload):
        video = next(s for s in payload['streams'] if s['codec_type']=='video')
        audio = next(s for s in payload['streams'] if s['codec_type']=='audio')
        return float(audio['start_time']) - float(video['start_time'])
    assert offset(after) == pytest.approx(offset(before), abs=.003)
    out_video = next(s for s in after['streams'] if s['codec_type']=='video')
    assert out_video['codec_name'] == 'hevc'
    assert out_video['pix_fmt'] == 'yuv420p10le'
    assert out_video['color_transfer'] == 'smpte2084'
    assert out_video['color_primaries'] == 'bt2020'
    assert out_video['color_space'] == 'bt2020nc'
    count = json.loads(_run([tools.ffprobe, '-v', 'error', '-count_frames', '-select_streams', 'v:0',
        '-show_entries', 'stream=nb_read_frames', '-of', 'json', str(output)]).stdout)['streams'][0]
    assert int(count['nb_read_frames']) == 25
    assert source.is_file()
    assert not list(tmp_path.glob('dragontools_comfyui_*'))
