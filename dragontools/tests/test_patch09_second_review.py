from pathlib import Path
from types import SimpleNamespace
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'dragon_hdr10plus_generator' / 'src'))

import pytest

from dragontools.tests.test_review09_hdr10plus import _context, _valid_payload
from dragontools.worker.hdrplus_pipeline_coordinator import HDRPlusPipelineCoordinator, HDRPlusPipelineHooks
from dragontools.worker.hdrplus_tool_runner import HDRPlusToolRunner
from dragontools.worker.dv_runtime_models import DVTempState
from dragontools.worker.tool_runner import ToolRunResult


def pipeline(tmp_path, *, exception=False):
    saved = {}

    class Encode:
        def encode(self, *, encoded_hevc, stream_donor, **kwargs):
            saved['root'] = encoded_hevc.parent
            encoded_hevc.write_bytes(b'video' * 1024)
            stream_donor.write_bytes(b'audio' * 512)
            return True

    def generate(video, metadata):
        Path(metadata).write_text(json.dumps(_valid_payload()), encoding='utf-8')
        return True

    def inject(*args):
        if exception:
            raise RuntimeError('late injection exception')
        return False

    hooks = HDRPlusPipelineHooks(
        extract_hevc_annexb=lambda *a, **k: True,
        extract_metadata=lambda *a: True,
        generate_metadata=generate,
        inject_metadata=inject,
        mux_output=lambda *a, **k: True,
        run_mux_tool=lambda *a, **k: True,
        verify_final=lambda *a: True,
        cleanup_tmp_sub=lambda *a: None,
    )
    coordinator = HDRPlusPipelineCoordinator(
        encode_service=Encode(), subtitle_service=None, subtitle_mux_service=None,
        subtitle_rules={}, log=lambda *a: None,
    )
    return coordinator, hooks, saved


def test_unexpected_hdr_exception_archives_encode_before_cleanup(tmp_path):
    coordinator, hooks, saved = pipeline(tmp_path, exception=True)
    result = coordinator.run(_context(tmp_path), hooks)
    assert not result.success
    assert Path(result.failure_archive_path, 'encoded.hevc').read_bytes() == b'video' * 1024
    assert not saved['root'].exists()


def test_partial_hdr_archive_preserves_uncopied_json_and_video(tmp_path, monkeypatch):
    import dragontools.worker.hdrplus_pipeline_coordinator as module
    coordinator, hooks, saved = pipeline(tmp_path)
    original = module.shutil.copy2

    def locked_metadata(source, target, *a, **k):
        if Path(source).name == 'metadata.json':
            raise PermissionError('locked metadata')
        return original(source, target, *a, **k)

    monkeypatch.setattr(module.shutil, 'copy2', locked_metadata)
    result = coordinator.run(_context(tmp_path), hooks)
    assert not result.success and not result.failure_archive_path
    assert saved['root'].joinpath('metadata.json').is_file()
    assert saved['root'].joinpath('encoded.hevc').is_file()
    assert str(saved['root'] / 'metadata.json') in result.failure_artifact_paths


def test_hdr_recovery_includes_audio_subtitle_donor(tmp_path):
    coordinator, hooks, _ = pipeline(tmp_path)
    result = coordinator.run(_context(tmp_path), hooks)
    assert Path(result.failure_archive_path, 'streams.mkv').read_bytes() == b'audio' * 512


@pytest.mark.parametrize('flag,code', [('aborted', 130), ('timed_out', 124)])
def test_hdr_tool_rc_zero_cannot_override_cancellation(flag, code):
    state = DVTempState()
    runner = HDRPlusToolRunner(
        run_tool_fn=lambda command, **kwargs: ToolRunResult(command=list(command), returncode=0, **{flag: True}),
        log_tool_failure_fn=lambda *a, **k: None, log=lambda *a: None, temp_state=state,
    )
    assert not runner.run_hdrplus(['tool'], label='inject', tool_name='tool')
    assert runner.run_hdrplus_rc(['tool']) == code


@pytest.mark.parametrize('value', [1.5, True, float('inf')])
def test_hdr_json_rejects_non_integer_luminance(value):
    from dragontools.core.hdr10plus_generation import validate_hdr10plus_json_payload
    payload = _valid_payload()
    payload['SceneInfo'][0]['LuminanceParameters']['AverageRGB'] = value
    valid, reason = validate_hdr10plus_json_payload(payload)
    assert not valid and 'AverageRGB' in reason


@pytest.mark.parametrize('value', [1.5, True, float('inf')])
def test_generator_rejects_non_integer_frame_count(tmp_path, value):
    from dragontools.worker.hdr10plus_generator_client import HDR10PlusGeneratorClient
    exe = tmp_path / 'generator.exe'
    exe.write_bytes(b'stub')
    output = tmp_path / 'meta.json'

    def run(command, **kwargs):
        output.write_text(json.dumps(_valid_payload(frames=1)), encoding='utf-8')
        return ToolRunResult(command=list(command), returncode=0, stdout=json.dumps({'success': True, 'frames': value, 'scenes': 1}))

    result = HDR10PlusGeneratorClient(str(exe), run_tool_fn=run).analyze(tmp_path / 'source.hevc', output)
    assert not result.success


def test_generator_rejects_response_for_another_input(tmp_path):
    from dragontools.worker.hdr10plus_generator_client import HDR10PlusGeneratorClient
    exe = tmp_path / 'generator.exe'
    exe.write_bytes(b'stub')
    output = tmp_path / 'meta.json'

    def run(command, **kwargs):
        output.write_text(json.dumps(_valid_payload()), encoding='utf-8')
        return ToolRunResult(command=list(command), returncode=0, stdout=json.dumps({'success': True, 'frames': 2, 'scenes': 1, 'input': str(tmp_path / 'other.hevc')}))

    result = HDR10PlusGeneratorClient(str(exe), run_tool_fn=run).analyze(tmp_path / 'source.hevc', output)
    assert not result.success and result.error == 'INPUT_PATH_MISMATCH'


def test_generator_client_output_collision_preserves_source(tmp_path):
    from dragontools.worker.hdr10plus_generator_client import HDR10PlusGeneratorClient
    source = tmp_path / 'source.hevc'
    source.write_bytes(b'original video')
    result = HDR10PlusGeneratorClient('missing').analyze(source, source)
    assert not result.success
    assert source.read_bytes() == b'original video'


def test_standalone_generator_output_collision_preserves_source(tmp_path, capsys):
    from dragon_hdr10plus_generator.cli import main
    source = tmp_path / 'source.mkv'
    source.write_bytes(b'original video')
    assert main(['analyze', '--input', str(source), '--output', str(source)]) == 2
    assert source.read_bytes() == b'original video'
    assert json.loads(capsys.readouterr().out)['error'] == 'OUTPUT_INPUT_COLLISION'


def test_hdr_encoder_mutable_options_do_not_modify_job_snapshot():
    from dragontools.worker.hdrplus_runtime_models import HDRPlusEncoderConfig
    config = HDRPlusEncoderConfig.create(codec='h265', crf=22, preset='medium', encoder_options={'nested': {'values': [1]}})
    config.mutable_encoder_options()['nested']['values'].append(2)
    assert config.encoder_options['nested']['values'] == [1]


@pytest.mark.parametrize('stream_index', [True, 1.5, -1])
def test_hdr_stream_extractor_rejects_invalid_global_index(tmp_path, stream_index):
    from dragontools.worker.hdrplus_stream_service import HDRPlusStreamService
    calls = []
    output = tmp_path / 'video.hevc'

    def run(command, **kwargs):
        calls.append(command)
        output.write_bytes(b'v' * 2048)
        return True

    assert not HDRPlusStreamService(ffmpeg_path='ffmpeg', log=lambda *a: None).extract_hevc_annexb('source.mkv', str(output), run_tool=run, stream_index=stream_index)
    assert calls == []


@pytest.mark.parametrize('payload', ['', '{}', '{"streams":{}}', '{"streams":[true]}'])
def test_hdr_mp4_audio_probe_rejects_malformed_inventory(tmp_path, payload):
    from dragontools.worker.hdrplus_mux_service import HDRPlusMuxService
    donor = tmp_path / 'streams.mkv'
    donor.write_bytes(b'd' * 2048)
    service = HDRPlusMuxService(tools=SimpleNamespace(ffprobe='ffprobe'), log=lambda *a: None, run_mux_tool=lambda *a, **k: True,
        capture_tool=lambda command, **kwargs: ToolRunResult(command=list(command), returncode=0, stdout=payload))
    assert service.probe_mp4_audio(donor) is None


@pytest.mark.parametrize('container', ['mkv', 'mp4'])
def test_hdr_mux_rejects_missing_required_donor(tmp_path, container):
    from dragontools.worker.hdrplus_mux_service import HDRPlusMuxService
    video = tmp_path / 'injected.hevc'
    output = tmp_path / ('out.' + container)
    video.write_bytes(b'v' * 2048)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        output.write_bytes(b'o' * 2048)
        return True

    service = HDRPlusMuxService(tools=SimpleNamespace(mkvmerge='mkvmerge', mp4box='MP4Box'), log=lambda *a: None, run_mux_tool=run, capture_tool=None)
    args = (str(video), str(tmp_path / 'missing.mkv'), str(output))
    result = service.mux_mkv(*args) if container == 'mkv' else service.mux_mp4(*args, tmp_dir=tmp_path)
    assert not result and calls == []


@pytest.mark.parametrize('filters', [['-vf', 'fps=25'], ['-vf', 'reverse'], ['-r', '25']])
def test_preserved_hdr_metadata_rejects_changed_timeline(tmp_path, filters):
    from dragontools.tests.test_review09_hdr10plus import _media
    from dataclasses import replace
    coordinator, hooks, _ = pipeline(tmp_path)
    context = replace(_context(tmp_path, media=_media(hdrplus=True), generate=False), vf_args=tuple(filters))
    assert not coordinator._preflight(context, hooks)


@pytest.mark.parametrize('container', ['mkv', 'mp4'])
def test_hdr_postprocess_late_exception_retains_candidate_and_original(tmp_path, container):
    from dataclasses import replace
    coordinator, hooks, saved = pipeline(tmp_path)
    output = tmp_path / ('out.' + container)
    output.write_bytes(b'original' * 512)

    def extract(source, target, **kwargs):
        Path(target).write_bytes(b'video' * 1024)
        saved['root'] = Path(target).parent
        return True

    def inject(video, metadata, target):
        Path(target).write_bytes(b'injected' * 512)
        return True

    def mux(video, donor, target, **kwargs):
        Path(target).write_bytes(b'candidate' * 512)
        raise RuntimeError('late mux exception')

    hooks = replace(hooks, extract_hevc_annexb=extract, inject_metadata=inject, mux_output=mux)
    result = coordinator.postprocess_existing_output(_context(tmp_path, output=output, container=container), hooks)
    assert not result.success and result.preserve_failed_output
    assert output.read_bytes() == b'original' * 512
    assert Path(result.failure_archive_path, 'candidate.' + container).read_bytes() == b'candidate' * 512


def test_generator_frame_count_matches_records_without_summary(tmp_path):
    from dragontools.worker.hdr10plus_generator_client import HDR10PlusGeneratorClient
    exe = tmp_path / 'generator.exe'
    exe.write_bytes(b'stub')
    output = tmp_path / 'meta.json'

    def run(command, **kwargs):
        output.write_text('{"SceneInfo":[{"SequenceFrameIndex":0}]}', encoding='utf-8')
        return ToolRunResult(command=list(command), returncode=0, stdout='{"success":true,"frames":2,"scenes":1}')

    result = HDR10PlusGeneratorClient(str(exe), run_tool_fn=run).analyze(tmp_path / 'source.hevc', output)
    assert not result.success and result.error == 'FRAME_COUNT_MISMATCH'


@pytest.mark.parametrize('filter_text', ['transpose=1', 'zscale=w=1280:h=720', 'crop=128:72', 'fps=25', 'reverse'])
def test_av1_metadata_rejects_unsupported_picture_or_timeline_change(monkeypatch, filter_text):
    from dragontools.tests.test_av1_metadata_pipeline import _media, _request, _Progress, _Tools
    from dragontools.worker.av1_metadata_pipeline import AV1HDR10PlusPipeline
    progress = _Progress()
    runner = AV1HDR10PlusPipeline(tools=_Tools(), progress_runner=progress, temp_state=DVTempState())
    monkeypatch.setattr(runner, '_ffmpeg_help_contains', lambda *a: (True, 'libaom'))
    monkeypatch.setattr('dragontools.worker.av1_metadata_pipeline.inspect_dynamic_hdr_with_mediainfo', lambda *a: SimpleNamespace(hdr10plus=True))
    result = runner.execute(_request(_media(hdrplus=True), pipeline='av1_hdrplus', vf_args=['-vf', filter_text, '-map', '0:v:0']))
    assert not result.success and progress.commands == []


@pytest.mark.parametrize('profile', [None, 'Ja', '8.1'])
def test_av1_dv_requires_proven_final_profile_and_retains_completed_encode(monkeypatch, profile):
    from dragontools.tests.test_av1_metadata_pipeline import _media, _request, _Progress, _Tools
    from dragontools.worker.av1_metadata_pipeline import AV1DolbyVisionPipeline
    runner = AV1DolbyVisionPipeline(tools=_Tools(), progress_runner=_Progress(), temp_state=DVTempState())
    monkeypatch.setattr(runner, '_ffmpeg_help_contains', lambda *a: (True, 'dolbyvision'))
    monkeypatch.setattr(runner, '_check_source', lambda *a: True)
    monkeypatch.setattr('dragontools.worker.av1_metadata_pipeline.inspect_dynamic_hdr_with_mediainfo', lambda *a: SimpleNamespace(dolby_vision=True, dolby_vision_profile=profile))
    monkeypatch.setattr(runner, '_fallback_analysis', lambda *a: None)
    result = runner.execute(_request(_media(dv=True), pipeline='av1_dv'))
    assert not result.success and result.preserve_failed_output


def test_hdr_mp4_audio_uses_global_index_and_keeps_default_flag(tmp_path):
    from dragontools.worker.hdrplus_mux_service import HDRPlusMuxService
    calls = []
    donor = tmp_path / 'streams.mkv'
    donor.write_bytes(b'a' * 2048)
    video = tmp_path / 'video.hevc'
    video.write_bytes(b'v' * 2048)
    output = tmp_path / 'out.mp4'

    def run(command, **kwargs):
        calls.append(command)
        Path(command[-1] if command[0] == 'ffmpeg' else command[command.index('-new') + 1]).write_bytes(b'x' * 2048)
        return True

    inventory = {'streams': [{'index': 4, 'codec_name': 'aac', 'tags': {'language': 'deu'}, 'disposition': {'default': 0}}]}
    service = HDRPlusMuxService(tools=SimpleNamespace(ffmpeg='ffmpeg', ffprobe='ffprobe', mp4box='MP4Box'), log=lambda *a: None, run_mux_tool=run,
        capture_tool=lambda command, **kwargs: ToolRunResult(command=list(command), returncode=0, stdout=json.dumps(inventory)))
    assert service.mux_mp4(str(video), str(donor), str(output), tmp_dir=tmp_path)
    assert calls[0][calls[0].index('-map') + 1] == '0:4'
    assert any(':lang=deu:disable' in value for value in calls[-1])


def test_hdr_timeout_does_not_start_annexb_fallback(tmp_path):
    from dataclasses import replace
    from dragontools.worker.hdrplus_pipeline_coordinator import HDRPlusPipelinePaths
    from dragontools.tests.test_review09_hdr10plus import _media
    coordinator, hooks, _ = pipeline(tmp_path)
    calls = []
    runner = HDRPlusToolRunner(run_tool_fn=lambda cmd, **kwargs: ToolRunResult(command=list(cmd), returncode=124, timed_out=True),
        log_tool_failure_fn=lambda *a, **k: None, log=lambda *a: None, temp_state=DVTempState())

    def metadata(source, target):
        return runner.run_hdrplus(['tool'], label='extract', tool_name='tool')

    hooks = replace(hooks, extract_metadata=metadata, extract_hevc_annexb=lambda *a, **k: calls.append(a) or False)
    # The façade binds this cancellation contract to the tool runner.
    if 'extract_interrupted' in hooks.__dataclass_fields__:
        hooks = replace(hooks, extract_interrupted=lambda: runner.interrupted)
    assert not coordinator._step_extract_metadata(_context(tmp_path, media=_media(hdrplus=True), generate=False), HDRPlusPipelinePaths.create(tmp_path), hooks)
    assert calls == []


@pytest.mark.parametrize('index', [True, 1.5, -1, None])
def test_hdr_extract_rejects_invalid_analyzed_primary_before_container_tool(tmp_path, index):
    from dataclasses import replace
    from dragontools.worker.hdrplus_pipeline_coordinator import HDRPlusPipelinePaths
    from dragontools.tests.test_review09_hdr10plus import _media
    coordinator, hooks, _ = pipeline(tmp_path)
    calls = []
    hooks = replace(hooks, extract_metadata=lambda *a: calls.append(a) or True)
    assert not coordinator._step_extract_metadata(_context(tmp_path, media=_media(index=index, hdrplus=True), generate=False), HDRPlusPipelinePaths.create(tmp_path), hooks)
    assert calls == []


def test_hdr_callback_internal_type_error_does_not_repeat_extraction(tmp_path):
    from dataclasses import replace
    from dragontools.worker.hdrplus_pipeline_coordinator import HDRPlusPipelinePaths
    from dragontools.tests.test_review09_hdr10plus import _media
    coordinator, hooks, _ = pipeline(tmp_path)
    calls = []

    def extract(*args, **kwargs):
        calls.append(args)
        raise TypeError('internal callback failure')

    hooks = replace(hooks, extract_metadata=lambda *a: False, extract_hevc_annexb=extract)
    with pytest.raises(TypeError, match='internal callback failure'):
        coordinator._step_extract_metadata(_context(tmp_path, media=_media(hdrplus=True), generate=False), HDRPlusPipelinePaths.create(tmp_path), hooks)
    assert len(calls) == 1


@pytest.mark.parametrize('operation', ['extract', 'inject_video', 'inject_json', 'verify'])
def test_hdr_bitstream_paths_cannot_delete_a_source_or_expected_metadata(tmp_path, operation):
    from dragontools.worker.hdr10plus_bitstream_service import HDR10PlusBitstreamService
    source = tmp_path / 'video.hevc'
    source.write_bytes(b'video' * 512)
    metadata = tmp_path / 'meta.json'
    metadata.write_text(json.dumps(_valid_payload()), encoding='utf-8')
    original = source.read_bytes(), metadata.read_bytes()
    calls = []
    run = lambda *a, **k: calls.append(a) or 1
    service = HDR10PlusBitstreamService(hdr10plus_tool_path='tool', log=lambda *a: None)
    if operation == 'extract':
        result = service.extract_metadata(run, source_stream=source, output_json=source)
    elif operation.startswith('inject'):
        result = service.inject_metadata(run, input_hevc=source, metadata_json=metadata, output_hevc=source if operation == 'inject_video' else metadata)
    else:
        result = service.verify_metadata(run, source_stream=source, scratch_json=metadata, expected_json=metadata)
    assert not result and calls == []
    assert (source.read_bytes(), metadata.read_bytes()) == original
