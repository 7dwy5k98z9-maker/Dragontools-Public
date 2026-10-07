"""Real decoded frame sequence and generator injection into HEVC."""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'dragon_hdr10plus_generator' / 'src'))
import pytest
from dragontools.tests.ci_requirements import external_media_environment
from dragontools.tests.test_real_dv_hdr_integration import _run, _make_hevc

pytestmark = pytest.mark.dv_hdr_integration


def test_real_vfr_generator_measures_each_presentation_frame_once(tmp_path):
    from dragon_hdr10plus_generator.analyzer.decoder import probe_video
    from dragon_hdr10plus_generator.analyzer.scanner import scan_pq_video
    from dragon_hdr10plus_generator.cli import main
    env = external_media_environment()
    assert not env.missing
    source = tmp_path / 'Variable Bildfolge Überprüfung.mkv'
    _run([env.ffmpeg, '-y', '-loglevel', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=128x72:rate=24:duration=1',
          '-vf', "select='eq(n,0)+eq(n,1)+eq(n,2)+eq(n,8)+eq(n,12)+eq(n,13)+eq(n,21)+eq(n,22)'",
          '-fps_mode', 'passthrough', '-c:v', 'libx265', '-preset', 'ultrafast',
          '-x265-params', 'log-level=error:colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc',
          '-pix_fmt', 'yuv420p10le', '-color_primaries', 'bt2020',
          '-color_trc', 'smpte2084', '-colorspace', 'bt2020nc', str(source)])
    probe = probe_video(source, ffprobe=env.ffprobe)
    scan = scan_pq_video(source, probe, ffmpeg=env.ffmpeg, analysis_width=128)
    assert len(scan.frames) == 8
    metadata = tmp_path / 'metadata.json'
    assert main(['analyze', '--input', str(source), '--output', str(metadata), '--ffmpeg', env.ffmpeg, '--ffprobe', env.ffprobe]) == 0
    assert len(json.loads(metadata.read_text(encoding='utf-8'))['SceneInfo']) == 8


@pytest.mark.parametrize('container', ['mkv', 'mp4'])
def test_real_generated_hdr_metadata_injection_and_final_container_proof(tmp_path, container):
    from dragon_hdr10plus_generator.cli import main
    from dragontools.worker.hdr10plus_bitstream_service import HDR10PlusBitstreamService
    from dragontools.worker.dv_command_runner import DVCommandRunner
    from dragontools.worker.dv_runtime_models import DVTempState
    from dragontools.worker.hdrplus_mux_service import HDRPlusMuxService
    from dragontools.worker.hdrplus_stream_service import HDRPlusStreamService
    from dragontools.worker.tool_runner import run_tool
    from types import SimpleNamespace
    env = external_media_environment()
    assert not env.missing
    encoded = tmp_path / 'encoded.hevc'
    _make_hevc(ffmpeg=env.ffmpeg, target=encoded, frames=10)
    tagged = tmp_path / 'encoded_PQ.hevc'
    _run([env.ffmpeg, '-y', '-loglevel', 'error', '-i', str(encoded), '-c:v', 'copy',
          '-bsf:v', 'hevc_metadata=colour_primaries=9:transfer_characteristics=16:matrix_coefficients=9',
          '-f', 'hevc', str(tagged)])
    encoded = tagged
    metadata = tmp_path / 'metadata.json'
    assert main(['analyze', '--input', str(encoded), '--output', str(metadata), '--ffmpeg', env.ffmpeg, '--ffprobe', env.ffprobe]) == 0
    assert len(json.loads(metadata.read_text(encoding='utf-8'))['SceneInfo']) == 10
    runner = DVCommandRunner(log=lambda *a: None, verbose_log=lambda *a: None, no_window_kwargs=lambda: {}, temp_state=DVTempState())
    run = runner.adapter(timeout=60, label='real HDR metadata')
    service = HDR10PlusBitstreamService(hdr10plus_tool_path=env.hdr10plus_tool, log=lambda *a: None)
    injected = tmp_path / 'injected.hevc'
    assert service.inject_metadata(run, input_hevc=encoded, metadata_json=metadata, output_hevc=injected)
    tools = SimpleNamespace(ffmpeg=env.ffmpeg, ffprobe=env.ffprobe, mp4box=env.mp4box, mkvmerge=os.environ['DRAGONTOOLS_MKVMERGE'])
    checked = lambda command, **kwargs: run(command) in kwargs.get('accepted_returncodes', (0,))
    mux = HDRPlusMuxService(tools=tools, log=lambda *a: None, run_mux_tool=checked, capture_tool=run_tool)
    output = tmp_path / ('Film Überprüfung.' + container)
    assert (mux.mux_mkv(str(injected), '', str(output)) if container == 'mkv' else mux.mux_mp4(str(injected), '', str(output), tmp_dir=tmp_path))
    verifier = HDRPlusStreamService(ffmpeg_path=env.ffmpeg, log=lambda *a: None)
    assert verifier.verify_final_hdr10plus(str(output), metadata, run_tool=checked, run_tool_rc=run, bitstream_service=service)


@pytest.mark.parametrize('pipeline_name,container', [
    ('av1_hdrplus', 'mkv'), ('av1_hdrplus', 'mp4'), ('av1_dv', 'mkv'), ('av1_dv', 'mp4'),
])
def test_real_native_av1_keeps_per_frame_dynamic_metadata(tmp_path, pipeline_name, container):
    from types import SimpleNamespace
    from dragon_hdr10plus_generator.cli import main
    from dragontools.core.media_analyzer import analyze_media
    from dragontools.tests.test_real_dv_hdr_integration import _make_pq_hevc, _DOVI_GENERATOR_CONFIG
    from dragontools.worker.av1_metadata_pipeline import AV1DolbyVisionPipeline, AV1HDR10PlusPipeline
    from dragontools.worker.dv_runtime_models import DVTempState
    from dragontools.worker.workflow_models import PipelineExecutionRequest
    from dragontools.worker.tool_runner import run_tool
    env = external_media_environment()
    assert not env.missing
    base = tmp_path / 'pq.hevc'
    _make_pq_hevc(ffmpeg=env.ffmpeg, target=base, frames=10)
    metadata = tmp_path / 'hdr.json'
    assert main(['analyze', '--input', str(base), '--output', str(metadata), '--ffmpeg', env.ffmpeg, '--ffprobe', env.ffprobe]) == 0
    hdr = tmp_path / 'hdr.hevc'
    _run([env.hdr10plus_tool, 'inject', '-i', str(base), '-j', str(metadata), '-o', str(hdr)])
    config = tmp_path / 'dovi.json'
    config.write_text(json.dumps(dict(_DOVI_GENERATOR_CONFIG, length=10)), encoding='utf-8')
    rpu = tmp_path / 'metadata.rpu'
    _run([env.dovi_tool, 'generate', '-j', str(config), '-o', str(rpu)])
    combined = tmp_path / 'combined.hevc'
    _run([env.dovi_tool, 'inject-rpu', '-i', str(hdr), '--rpu-in', str(rpu), '-o', str(combined)])
    source = tmp_path / 'Quelle Überprüfung.mkv'
    _run([os.environ['DRAGONTOOLS_MKVMERGE'], '-o', str(source), str(combined)])
    tools = SimpleNamespace(ffmpeg=env.ffmpeg, ffprobe=env.ffprobe, mediainfo='')
    media = analyze_media(str(source), tools)
    assert media.has_dv and media.has_hdrplus
    output = tmp_path / ('Ausgabe Überprüfung.' + container)
    state = DVTempState()

    def progress(command, *args):
        result = run_tool(command, timeout_s=90, label='real native AV1')
        state.stderr = result.tail(20)
        return result.returncode

    pipeline_type = AV1HDR10PlusPipeline if pipeline_name == 'av1_hdrplus' else AV1DolbyVisionPipeline
    pipeline = pipeline_type(tools=tools, progress_runner=progress, temp_state=state)
    plan = SimpleNamespace(crop=None, vf_args=['-map', '0:v:0'], audio_args=['-an'], audio_input_args=[], sn=['-sn'], burn_sub_or_vf=None)
    request = PipelineExecutionRequest(pipeline=pipeline_name, input_path=str(source), output_path=str(output), container=container,
        media_info=media, plan=plan, override={}, strip_only=False, duration_ms=417, codec='av1', crf=28, preset='8',
        encoder_options={'encoder': 'cpu'}, preserve_hdrplus=pipeline_name == 'av1_hdrplus')
    result = pipeline.execute(request)
    assert result.success, (result.failure_reason, result.tool_output)
    kind = 'HDR Dynamic Metadata SMPTE2094-40 (HDR10+)' if pipeline_name == 'av1_hdrplus' else 'Dolby Vision Metadata'

    def frame_metadata(path):
        probe = _run([env.ffprobe, '-v', 'error', '-show_frames', '-of', 'json', str(path)])
        frames = json.loads(probe.stdout)['frames']
        assert len(frames) == 10
        return [next(side for side in frame.get('side_data_list', []) if side.get('side_data_type') == kind) for frame in frames]

    assert frame_metadata(source) == frame_metadata(output)
    if pipeline_name == 'av1_dv':
        assert result.verified_dolby_vision and analyze_media(str(output), tools).dv_profile_major == 10
    else:
        assert result.verified_hdr10plus
