from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from dragontools.core.sdr_hdr_enhancement import decide_sdr_hdr_enhancement
from dragontools.tests.test_patch_al_comfyui_video_worker import _media, _ready_options
from dragontools.worker import comfyui_video_worker as module
from dragontools.worker.comfyui_client import ComfyUIResult


def render(tmp_path, monkeypatch, *, frames=100, log=None, worker=None, **changes):
    output = tmp_path / 'HDR ä.mkv'
    manifest = tmp_path / 'manifest.json'
    calls = []
    class Client:
        def __init__(self, *_a, **_kw): pass
        def queue_workflow(self, workflow):
            calls.append(workflow)
            output.write_bytes(b'new-video')
            manifest.write_text(json.dumps({'success': True, 'frames': frames}), encoding='utf-8')
            return ComfyUIResult(True, prompt_id='owned-job')
        def history(self, job):
            return ComfyUIResult(True, payload={job: {'status': {'completed': True, 'status_str': 'success'}}})
        def cancel(self, job):
            return ComfyUIResult(False, error='CANCEL_FAILED', prompt_id=job)
    monkeypatch.setattr(module, 'ComfyUIClient', Client)
    args = dict(input_path=str(tmp_path / 'source.mkv'), output_path=str(output), media_info=_media(),
        encoder_options={'_comfyui_model_profile': 'hdrtvdm_lsn_3dm'},
        decode_args=['-map', '0:v:0'], encode_args=['-c:v', 'libx265'], hdr_output_args=[],
        manifest_path=str(manifest))
    args.update(changes)
    service = module.ComfyUIHDRVideoService(tools=NS(ffmpeg='ffmpeg', ffprobe='ffprobe'), worker=worker, log=log)
    return service.render(**args), calls, output, manifest


@pytest.mark.parametrize('collision', ['output', 'manifest', 'same_artifacts', 'hardlink'])
def test_source_and_job_paths_never_alias_before_cleanup(tmp_path, monkeypatch, collision):
    source = tmp_path / 'source.mkv'
    source.write_bytes(b'irreplaceable-source')
    changes = {}
    if collision == 'output': changes['output_path'] = str(source)
    if collision == 'manifest': changes['manifest_path'] = str(source)
    if collision == 'same_artifacts': changes['manifest_path'] = str(tmp_path / 'HDR ä.mkv')
    if collision == 'hardlink':
        (tmp_path / 'HDR ä.mkv').hardlink_to(source)
    result, calls, *_ = render(tmp_path, monkeypatch, **changes)
    assert not result.success
    assert result.error == 'PATH_COLLISION'
    assert source.read_bytes() == b'irreplaceable-source'
    assert calls == []


@pytest.mark.parametrize('fps', ['0', '-25', 'nan', 'inf', '25/0', 'nonsense'])
def test_preflight_and_worker_share_valid_cfr_contract(fps):
    media = _media(fps=fps)
    decision = decide_sdr_hdr_enhancement(media, target_codec='h265', encoder_options=_ready_options())
    assert not decision.applied


@pytest.mark.parametrize('frames', [True, 100.9, float('inf'), '100.9'])
def test_manifest_counts_are_discrete_not_rounded(tmp_path, monkeypatch, frames):
    result, *_ = render(tmp_path, monkeypatch, frames=frames)
    assert not result.success
    assert result.error in {'NO_FRAMES', 'MANIFEST_INVALID'}


@pytest.mark.parametrize('filters', [['-vf', 'fps=12'], ['-vf', 'setpts=2*PTS'], ['-r', '30'], ['-vf', 'reverse']])
def test_temporal_changes_never_queue_fixed_source_fps(tmp_path, monkeypatch, filters):
    result, calls, *_ = render(tmp_path, monkeypatch, decode_args=['-map', '0:v:0'] + filters)
    assert not result.success
    assert result.error == 'UNSUPPORTED_TIMING'
    assert calls == []


def test_explicit_custom_model_profile_is_not_overwritten_by_default(tmp_path, monkeypatch):
    result, calls, *_ = render(tmp_path, monkeypatch, encoder_options={'comfyui_model_profile': 'custom'})
    assert not result.success
    assert result.error == 'WORKFLOW_MISSING'
    assert calls == []


def test_unknown_model_profile_never_defaults_to_hdrtvdm(tmp_path, monkeypatch):
    result, calls, *_ = render(tmp_path, monkeypatch, encoder_options={'comfyui_model_profile': 'anime-explicit'})
    assert not result.success and result.error == 'WORKFLOW_MISSING'
    assert calls == []


def test_cancel_failure_retains_artifacts_and_requests_local_stop(tmp_path, monkeypatch):
    output = tmp_path / 'partial.mkv'
    manifest = tmp_path / 'manifest.json'
    class Client:
        def __init__(self, *_a, **_kw): pass
        def queue_workflow(self, _workflow):
            output.write_bytes(b'active-child-output')
            return ComfyUIResult(True, prompt_id='running-owned-job')
        def history(self, _job):
            return ComfyUIResult(False, error='HISTORY_FAILED')
        def cancel(self, _job):
            return ComfyUIResult(False, error='CANCEL_FAILED')
    monkeypatch.setattr(module, 'ComfyUIClient', Client)
    result = module.ComfyUIHDRVideoService(tools=NS(ffmpeg='ffmpeg')).render(
        input_path='source.mkv', output_path=str(output), media_info=_media(), encoder_options={},
        decode_args=['-map', '0:v:0'], encode_args=['-c:v', 'libx265'], hdr_output_args=[], manifest_path=str(manifest))
    assert not result.success
    assert result.preserve_artifacts is True
    assert output.read_bytes() == b'active-child-output'
    assert Path(str(manifest) + '.cancel').is_file()


def test_stale_source_index_fails_before_external_job(tmp_path, monkeypatch):
    media = _media()
    media.primary_video.index = True
    result, calls, *_ = render(tmp_path, monkeypatch, media_info=media)
    assert not result.success and result.error == 'INVALID_VIDEO_SELECTION'
    assert calls == []


def test_logger_failure_does_not_leave_job_unmanaged(tmp_path, monkeypatch):
    def logger(*_args): raise RuntimeError('detached GUI')
    result, calls, *_ = render(tmp_path, monkeypatch, log=logger)
    assert calls
    assert not result.success  # Non-media bytes must be rejected by the actual probe.
    assert result.error == 'OUTPUT_INVALID'


def test_success_manifest_does_not_prove_hdr_media(tmp_path, monkeypatch):
    result, *_ = render(tmp_path, monkeypatch)
    assert not result.success
    assert result.error == 'OUTPUT_INVALID'


def bridge(monkeypatch):
    # These cases exercise the real bridge's filesystem/pipe boundaries, with
    # unused model libraries stubbed. They do not claim to test neural inference.
    monkeypatch.setitem(sys.modules, 'torch', NS(Tensor=object))
    imageio_stub = NS()
    monkeypatch.setitem(sys.modules, 'imageio', NS(v2=imageio_stub))
    monkeypatch.setitem(sys.modules, 'imageio.v2', imageio_stub)
    path = Path(__file__).resolve().parents[2] / 'extras/comfyui/DragonTools_HDRTVDM/nodes.py'
    spec = importlib.util.spec_from_file_location('patch10_bridge', path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_bridge_source_alias_rejected_before_manifest_or_process(tmp_path, monkeypatch):
    node = bridge(monkeypatch)
    source = tmp_path / 'source.mkv'
    source.write_bytes(b'source')
    seen = []
    monkeypatch.setattr(node.subprocess, 'Popen', lambda *_a, **_kw: seen.append(True))
    with pytest.raises(ValueError, match='(?i)(collision|distinct|quelle)'):
        node.DragonHDRTVDMVideoConvert().convert_video({'device': NS(type='cpu')}, str(source), str(source), 'ffmpeg', '[]', '[]', '[]', 25, 1, 1, 1, str(tmp_path/'manifest.json'))
    assert source.read_bytes() == b'source'
    assert seen == []


def test_manifest_writer_survives_windows_replace_sharing_violation(tmp_path, monkeypatch):
    node = bridge(monkeypatch)
    def locked(*_a): raise PermissionError('[WinError 5] sharing violation')
    monkeypatch.setattr(Path, 'replace', locked)
    path = tmp_path / 'manifest.json'
    node._write_manifest(path, success=True, frames=100)
    assert json.loads(path.read_text(encoding='utf-8'))['frames'] == 100


def test_bridge_checks_per_job_stop_before_any_child(tmp_path, monkeypatch):
    node = bridge(monkeypatch)
    manifest = tmp_path / 'manifest.json'
    Path(str(manifest)+'.cancel').write_text('cancel', encoding='utf-8')
    seen = []
    monkeypatch.setattr(node.subprocess, 'Popen', lambda *_a, **_kw: seen.append(True))
    with pytest.raises(RuntimeError, match='(?i)cancel'):
        node.DragonHDRTVDMVideoConvert().convert_video({'device': NS(type='cpu')}, 'source.mkv', str(tmp_path/'out.mkv'), 'ffmpeg', '[]', '[]', '[]', 25, 1, 1, 1, str(manifest))
    assert seen == []


def test_unconfirmed_external_cancel_does_not_delete_workspace(tmp_path, monkeypatch):
    from dragontools.worker import standard_pipeline_runner as runner_module
    from dragontools.worker.workflow_models import PipelineExecutionRequest
    roots = []
    class Service:
        def __init__(self, **_kw): pass
        def render(self, **kw):
            Path(kw['output_path']).write_bytes(b'active-output')
            roots.append(Path(kw['output_path']).parent)
            return NS(success=False, error='ABORTED', message='stop pending', preserve_artifacts=True)
    monkeypatch.setattr(runner_module, 'ComfyUIHDRVideoService', Service)
    request = PipelineExecutionRequest('standard', 'source.mkv', str(tmp_path/'out.mkv'), 'mkv', _media(),
        NS(vf_args=['-map','0:v:0'], audio_args=['-an'], sn=['-sn'], audio_input_args=[]), {}, False, 1000, 'h265', 23, 'fast',
        {'encoder':'cpu', '_sdr_hdr_applied':True, 'sdr_hdr_backend':'comfyui'})
    result = runner_module.StandardPipelineRunner(tools=NS(ffmpeg='ffmpeg'), codec='h265', crf=23,
        preset='fast', encoder_options={}, progress_runner=lambda *_: 0).execute(request)
    assert not result.success
    assert roots[0].is_dir()
    assert (roots[0]/'hdrtvdm_video.mkv').read_bytes() == b'active-output'
    assert result.failure_artifact_paths


def test_unknown_backend_never_silently_runs_ffmpeg():
    decision = decide_sdr_hdr_enhancement(_media(), target_codec='h265', encoder_options={
        'sdr_hdr_enabled': True, 'sdr_hdr_backend': 'anime-custom', '_sdr_hdr_libplacebo_available': True})
    assert not decision.applied
    assert 'Backend' in decision.reason


@pytest.mark.parametrize('aborted,auto_start', [(True, True), (False, 'false')])
def test_runtime_does_not_launch_after_abort_or_text_false(tmp_path, monkeypatch, aborted, auto_start):
    from dragontools.worker import comfyui_runtime as runtime
    calls = []
    down = ComfyUIResult(False, error='SERVICE_UNREACHABLE')
    class Client:
        def __init__(self, *_a, **_kw): pass
        def health(self): return down
    monkeypatch.setattr(runtime, 'ComfyUIClient', Client)
    monkeypatch.setattr(runtime, '_auto_start_and_wait', lambda *_a, **_kw: calls.append(True) or down)
    runtime.configure_comfyui_runtime(NS(abort_requested=aborted, log=lambda *_: None), NS(comfyui=''), {'comfyui_auto_start': auto_start})
    assert calls == []


def test_failed_launcher_does_not_block_valid_retry_with_cooldown(tmp_path, monkeypatch):
    from dragontools.worker import comfyui_runtime as runtime
    launcher = tmp_path / 'run.bat'
    launcher.write_text('@echo off', encoding='utf-8')
    runtime._COMFYUI_START_ATTEMPTS.clear()
    down = ComfyUIResult(False)
    calls = []
    def launch(_path):
        calls.append(True)
        raise OSError('temporary launcher failure')
    monkeypatch.setattr(runtime, '_launch_file', launch)
    for _ in range(2):
        runtime._auto_start_and_wait(NS(abort_requested=False, log=lambda *_: None), NS(comfyui=''),
            {'comfyui_start_file': str(launcher)}, NS(health=lambda: down), initial_health=down)
    assert calls == [True, True]


def test_lost_queue_response_retains_unique_tree_and_signals_bridge(tmp_path, monkeypatch):
    class Client:
        def __init__(self, *_a, **_kw): pass
        def queue_workflow(self, _workflow): return ComfyUIResult(False, error='QUEUE_FAILED', message='response lost')
    monkeypatch.setattr(module, 'ComfyUIClient', Client)
    manifest = tmp_path / 'manifest.json'
    result = module.ComfyUIHDRVideoService(tools=NS(ffmpeg='ffmpeg')).render(
        input_path='source.mkv', output_path=str(tmp_path/'out.mkv'), media_info=_media(), encoder_options={},
        decode_args=['-map','0:v:0'], encode_args=['-c:v','libx265'], hdr_output_args=[], manifest_path=str(manifest))
    assert not result.success and result.preserve_artifacts
    assert Path(str(manifest)+'.cancel').is_file()


def test_cancel_accepted_but_running_history_preserves_tree(tmp_path, monkeypatch):
    from dragontools.worker.comfyui_job_monitor import cancel_owned_job
    client = NS(cancel=lambda job: ComfyUIResult(True, prompt_id=job, payload={'cancelled':True}),
        history=lambda job: ComfyUIResult(True, payload={job:{'status':{'completed':False, 'status_str':'running'}}}))
    result = cancel_owned_job(client, 'owned', tmp_path/'manifest.json', 'ABORTED', 'stop')
    assert result.preserve_artifacts and not result.success


def test_hdrtvdm_workflow_cannot_hide_dynamic_paths_in_unused_metadata():
    from dragontools.core.comfyui_hdr_models import builtin_hdrtvdm_workflow, required_node_classes, HDRTVDM_PROFILE
    from dragontools.core.comfyui_workflow import validate_comfyui_video_workflow
    workflow = builtin_hdrtvdm_workflow()
    workflow['2']['inputs']['output_video'] = 'D:/fixed/other-source.mkv'
    workflow['2']['_meta'] = {'unused': '{{OUTPUT_VIDEO}}'}
    with pytest.raises(ValueError):
        validate_comfyui_video_workflow(workflow, required_class_types=required_node_classes(HDRTVDM_PROFILE))


@pytest.mark.parametrize('damage', ['fps', 'count', 'codec', 'transfer', 'depth', 'audio', 'source_count', 'timed_out', 'aborted'])
def test_independent_probe_rejects_false_success(damage, monkeypatch):
    from copy import deepcopy
    from fractions import Fraction
    from dragontools.worker import comfyui_video_contract as contract
    video = {'index':0, 'codec_type':'video', 'codec_name':'hevc', 'color_primaries':'bt2020',
        'color_transfer':'smpte2084', 'color_space':'bt2020nc', 'pix_fmt':'yuv420p10le',
        'nb_read_frames':'100', 'avg_frame_rate':'24000/1001', 'start_time':'0'}
    output = {'streams':[deepcopy(video)], 'format':{'start_time':'0'}}
    source = {'streams':[deepcopy(video)], 'format':{'start_time':'2'}}
    source['streams'][0].update(index=3, start_time='2.2')
    if damage == 'fps': output['streams'][0]['avg_frame_rate'] = '25'
    if damage == 'count': output['streams'][0]['nb_read_frames'] = '99'
    if damage == 'codec': output['streams'][0]['codec_name'] = 'h264'
    if damage == 'transfer': output['streams'][0]['color_transfer'] = 'bt709'
    if damage == 'depth': output['streams'][0]['pix_fmt'] = 'yuv420p'
    if damage == 'audio': output['streams'].append({'codec_type':'audio'})
    if damage == 'source_count': source['streams'][0]['nb_read_frames'] = '101'
    calls = []
    def run(command, **kwargs):
        assert kwargs['abort_on_request'] is True
        assert kwargs['timeout_mode'] == 'inactivity'
        calls.append(command)
        return NS(returncode=0, stdout=json.dumps(output if command[-1]=='out.mkv' else source), stderr='',
            timed_out=damage=='timed_out', aborted=damage=='aborted')
    monkeypatch.setattr(contract, 'run_tool', run)
    result = contract.verify_comfyui_video(tools=NS(ffprobe='ffprobe'), worker=None, log=None,
        input_path='source.mkv', output_path='out.mkv', source_index=3, fps=Fraction(24000,1001), frames=100,
        encode_args=['-c:v','libx265'])
    assert not result.success


def test_probe_preserves_source_video_offset_and_global_primary_index(monkeypatch):
    from fractions import Fraction
    from dragontools.worker import comfyui_video_contract as contract
    video = {'index':0, 'codec_type':'video', 'codec_name':'hevc', 'color_primaries':'bt2020',
        'color_transfer':'smpte2084', 'color_space':'bt2020nc', 'pix_fmt':'yuv420p10le',
        'nb_read_frames':'100', 'avg_frame_rate':'24000/1001', 'start_time':'0'}
    source_video = dict(video, index=3, start_time='2.2')
    def run(command, **kwargs):
        data = {'streams':[video], 'format':{'start_time':'0'}} if command[-1]=='out.mkv' else {
            'streams':[dict(source_video,index=0,nb_read_frames='1'), source_video], 'format':{'start_time':'2'}}
        return NS(returncode=0, stdout=json.dumps(data), stderr='', timed_out=False, aborted=False)
    monkeypatch.setattr(contract, 'run_tool', run)
    result = contract.verify_comfyui_video(tools=NS(ffprobe='ffprobe'), worker=None, log=None,
        input_path='source.mkv', output_path='out.mkv', source_index=3, fps=Fraction(24000,1001), frames=100,
        encode_args=['-c:v','libx265'])
    assert result.success and result.video_offset_s == pytest.approx(.2)


def test_comfy_decoder_pins_nonzero_primary_global_index(tmp_path, monkeypatch):
    media = _media()
    media.primary_video.index = 3
    result, calls, *_ = render(tmp_path, monkeypatch, media_info=media)
    assert calls
    assert json.loads(calls[0]['2']['inputs']['decode_args_json']) == ['-map','0:3']


def test_comfy_decoder_rejects_explicit_wrong_source_stream(tmp_path, monkeypatch):
    media = _media()
    media.primary_video.index = 3
    result, calls, *_ = render(tmp_path, monkeypatch, media_info=media, decode_args=['-map','0:1'])
    assert not result.success and result.error == 'INVALID_VIDEO_SELECTION'
    assert calls == []


def test_abort_while_waiting_for_shared_launcher_lock_returns_without_start(monkeypatch):
    from dragontools.worker import comfyui_runtime as runtime
    worker = NS(abort_requested=False, log=lambda *_: None)
    class Lock:
        def acquire(self, *, timeout):
            assert timeout <= .25
            worker.abort_requested = True
            return False
        def __enter__(self): raise AssertionError('blocking startup lock cannot check abort')
        def __exit__(self, *_): pass
    monkeypatch.setattr(runtime, '_COMFYUI_START_LOCK', Lock())
    down = ComfyUIResult(False)
    result = runtime._auto_start_and_wait(worker, NS(), {}, NS(health=lambda: pytest.fail('No API/launcher work after abort')), initial_health=down)
    assert result is down


def test_bridge_writer_abort_stops_child_before_closing_blocked_pipe(monkeypatch):
    import threading
    node = bridge(monkeypatch)
    stopped = []
    process = NS()
    writer = node._ProcessStdinWriter.__new__(node._ProcessStdinWriter)
    writer._stop = threading.Event()
    writer._thread = NS(is_alive=lambda: False)
    writer.process = process
    writer.stream = object()
    def stop(owned):
        assert owned is process
        stopped.append(True)
    def close(stream):
        assert stream is writer.stream
        assert stopped, 'Closing a pipe held by the writer thread can deadlock until the child exits.'
    monkeypatch.setattr(node, '_terminate', stop)
    monkeypatch.setattr(node, '_close_stream', close)
    writer.abort()


def test_zero_mux_returncode_does_not_destroy_verified_hdr_intermediate(tmp_path, monkeypatch):
    from dragontools.worker import standard_pipeline_runner as runner_module
    from dragontools.worker.workflow_models import PipelineExecutionRequest
    roots = []
    class Service:
        def __init__(self, **_kw): pass
        def render(self, **kw):
            Path(kw['output_path']).write_bytes(b'expensive-HDR-video')
            roots.append(Path(kw['output_path']).parent)
            return NS(success=True, error='', message='', frames=100, elapsed_s=0, peak_vram_bytes=0,
                video_offset_s=0, source_input_offset_s=0)
    monkeypatch.setattr(runner_module, 'ComfyUIHDRVideoService', Service)
    request = PipelineExecutionRequest('standard','source.mkv',str(tmp_path/'out.mkv'),'mkv',_media(),
        NS(vf_args=['-map','0:v:0'],audio_args=['-an'],sn=['-sn'],audio_input_args=[]),{},False,1000,'h265',23,'fast',
        {'encoder':'cpu','_sdr_hdr_applied':True,'sdr_hdr_backend':'comfyui'})
    # The mux claims success but produces no media, as with a broken wrapper.
    result = runner_module.StandardPipelineRunner(tools=NS(ffmpeg='ffmpeg', ffprobe='ffprobe'),codec='h265',crf=23,
        preset='fast',encoder_options={},progress_runner=lambda *_:0).execute(request)
    assert not result.success
    assert result.failure_stage == 'ComfyUI-HDR-Mux-Verifikation'
    assert (roots[0]/'hdrtvdm_video.mkv').read_bytes() == b'expensive-HDR-video'
    assert result.failure_artifact_paths


def test_model_nan_pixels_are_rejected_before_encoding(tmp_path, monkeypatch):
    import numpy as np
    from dragontools.tests.test_patch10_real_media import NumpyTensor
    node = bridge(monkeypatch)
    node.torch.from_numpy = NumpyTensor
    pixels = np.zeros((1,8,8,3), dtype=np.float32)
    pixels[0,0,0,0] = np.nan
    monkeypatch.setattr(node, '_convert_batch', lambda *_: NumpyTensor(pixels))
    writes = []
    process = NS(stdin=object(), poll=lambda: None)
    writer = NS(write=writes.append)
    with pytest.raises(ValueError, match='(?i)(finite|pixel|model)'):
        node._process_batch({}, [np.zeros((8,8,3), dtype=np.uint8)], process, writer, None,
            ffmpeg_path='ffmpeg', output=tmp_path/'out.mkv', encode_args=[], hdr_args=[], fps_num=25, fps_den=1)
    assert writes == []
