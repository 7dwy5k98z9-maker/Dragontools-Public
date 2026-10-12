"""Bitmap subtitle EOF must not add a far-future frame or truncate the movie."""
import json
import subprocess
from types import SimpleNamespace as NS

import pytest

from dragontools.core.models import SubtitleStream
from dragontools.worker.converter_video_filter_args import image_burn_vf_args
from dragontools.worker.duration_repair_policy import can_repair_duration
from dragontools.worker.output_verifier import OutputVerifier
from dragontools.worker.standard_pipeline_runner import StandardPipelineRunner
from dragontools.worker.workflow_models import PipelineExecutionRequest


@pytest.mark.parametrize('filters', [[], ['crop=1280:700:0:10', 'scale=160:90']])
def test_bitmap_overlay_continues_main_video_after_subtitle_eof(filters):
    stream = SubtitleStream(index=7, language='de', forced=True, title='', codec='hdmv_pgs_subtitle')
    args = image_burn_vf_args(NS(subtitle_streams=[stream]), stream, filters)
    graph = args[args.index('-filter_complex') + 1]
    assert 'overlay=eof_action=pass:repeatlast=0' in graph
    assert 'shortest=1' not in graph
    assert 'setpts' not in graph
    if filters:
        assert graph.index('overlay=') < graph.index('crop=') < graph.index('scale=')


def run(command, binary=False):
    result = subprocess.run([str(v) for v in command], capture_output=True, timeout=60,
                            **({} if binary else {'text': True, 'encoding': 'utf-8', 'errors': 'replace'}))
    assert result.returncode == 0, result.stderr[-3000:]
    return result.stdout


def probe(tools, path):
    return json.loads(run([tools.ffprobe, '-v', 'error', '-show_format', '-show_streams', '-of', 'json', path]))


def packets(tools, path):
    return json.loads(run([tools.ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_packets',
                          '-show_entries', 'packet=pts_time', '-of', 'json', path]))['packets']


@pytest.fixture(scope='module')
def bitmap_source(tmp_path_factory, qapp):
    from dragontools.tests.ci_requirements import external_media_environment, _resolve_tool
    from dragontools.tests.test_patch12_real_media import pgs_fixture
    environment = external_media_environment()
    merge = _resolve_tool('DRAGONTOOLS_MKVMERGE', 'mkvmerge.exe', 'mkvmerge')
    if not environment.ffmpeg or not environment.ffprobe or not merge:
        pytest.skip('Bitmap timing tests require FFmpeg, ffprobe and MKVToolNix')
    tools = NS(ffmpeg=environment.ffmpeg, ffprobe=environment.ffprobe)
    directory = tmp_path_factory.mktemp('bitmap_timing')
    video = directory / 'video.mkv'
    run([tools.ffmpeg, '-nostdin', '-y', '-v', 'error', '-f', 'lavfi', '-i',
         'color=c=black:size=1280x720:rate=24000/1001:duration=4', '-itsoffset', '0.8', '-f', 'lavfi', '-i',
         'sine=frequency=440:sample_rate=48000:duration=3', '-map', '0:v', '-map', '1:a',
         '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '1', '-c:a', 'aac', video])
    subtitle = pgs_fixture(directory / 'generated.sup', qapp)
    source = directory / 'bitmap-source.mkv'
    result = subprocess.run([merge, '-o', str(source), str(video), str(subtitle)], capture_output=True, timeout=60)
    assert result.returncode in {0, 1}, result.stderr[-2000:]
    return tools, source


@pytest.mark.media_integration
@pytest.mark.parametrize('codec', ['h264', 'h265'])
@pytest.mark.parametrize('container', ['mkv', 'mp4'])
def test_real_bitmap_encode_preserves_frames_audio_offset_and_visible_subtitles(bitmap_source, tmp_path, codec, container):
    tools, source = bitmap_source
    before = probe(tools, source)
    subtitle_info = next(s for s in before['streams'] if s['codec_type'] == 'subtitle')
    burn = SubtitleStream(index=subtitle_info['index'], language='de', forced=True, title='', codec='hdmv_pgs_subtitle')
    info = NS(is_hdr=False, video_streams=[], audio_streams=[], subtitle_streams=[burn])
    options = {'encoder': 'cpu', 'bf': 8, 'rc_lookahead': 40}
    plan = NS(vf_args=image_burn_vf_args(info, burn, ['scale=160:90']), audio_input_args=[],
              audio_args=['-map', '0:a:0', '-c:a', 'copy'], sn=['-sn'])
    output = tmp_path / ('output.' + container)
    commands = []
    def progress(command, *_):
        command = [command[0], '-threads', '2', '-filter_complex_threads', '1', *command[1:]]
        if '-x265-params' in command:
            index = command.index('-x265-params') + 1
            command[index] += ':pools=1:frame-threads=1'
        commands.append(command)
        run(command)
        return 0
    runner = StandardPipelineRunner(tools=tools, codec=codec, crf=22, preset='medium',
                                    encoder_options=options, progress_runner=progress)
    request = PipelineExecutionRequest(pipeline='standard', input_path=str(source), output_path=str(output),
        container=container, media_info=info, plan=plan, override={}, strip_only=False,
        duration_ms=4000, codec=codec, crf=22, preset='medium', encoder_options=options)
    assert runner.execute(request).success
    source_packets, output_packets = packets(tools, source), packets(tools, output)
    assert len(output_packets) == len(source_packets) == 96
    assert max(float(p['pts_time']) for p in output_packets) < 5
    after = probe(tools, output)
    assert float(after['format']['duration']) == pytest.approx(4, abs=.15)
    def offset(path, video_packets):
        # Matroska/MP4 headers account for AAC priming differently. Compare
        # the actual packet timelines instead of the container start_time.
        audio_packet = json.loads(run([tools.ffprobe, '-v', 'error', '-select_streams', 'a:0',
            '-read_intervals', '%+#1', '-show_packets', '-of', 'json', path]))['packets'][0]
        return float(audio_packet['pts_time']) - min(float(p['pts_time']) for p in video_packets)
    assert offset(output, output_packets) == pytest.approx(offset(source, source_packets), abs=.004)
    verification = OutputVerifier(ffprobe_path=tools.ffprobe).verify(str(output), container,
        expected_duration_ms=4000, source_has_audio=True)
    assert verification.ok, verification.messages
    assert not can_repair_duration(output_path=str(output), container=container, verify_result=verification,
                                  normal_remux_enabled=True, timestamp_repair_enabled=True)
    for moment, visible in [('0.2', False), ('0.9', True), ('2.8', False), ('3.9', False)]:
        frame = run([tools.ffmpeg, '-nostdin', '-v', 'error', '-ss', moment, '-i', output,
                     '-map', '0:v:0', '-frames:v', '1', '-pix_fmt', 'gray', '-f', 'rawvideo', 'pipe:1'], binary=True)
        assert len(frame) == 160 * 90
        assert (max(frame) > 100) == visible
