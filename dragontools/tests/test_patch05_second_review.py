from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace as NS

import pytest

from dragontools.core.models import MediaInfo, VideoStream
from dragontools.worker.converter_stream_args import ConverterStreamArgsHelper
from dragontools.worker.encode_plan import EncodePlan
from dragontools.worker.encode_plan_service import EncodePlanService
from dragontools.worker.encoder_args import _vid_args
from dragontools.worker.standard_pipeline_runner import StandardPipelineRunner
from dragontools.worker.workflow_models import PipelineExecutionRequest


def _media(index=3):
    return MediaInfo(path='source.mkv', video_streams=[VideoStream(index=index,
        codec='hevc', width=1920, height=1080, color_primaries='bt709',
        color_transfer='bt709', color_space='bt709')], audio_streams=[], subtitle_streams=[])


def _service(options=None, crop=None):
    worker = NS(log=lambda *args: None, subtitle_rules={},
        _logger=NS(info=lambda *args: None, decision=lambda *args: None))
    return EncodePlanService(codec='h265', encoder_options=options if options is not None else {},
        scale_mode='original', detect_imax_auto=lambda *args: False,
        detect_crop=crop or (lambda *args: None), probe_duration_ms=lambda *args: 1000,
        stream_args_helper=ConverterStreamArgsHelper(worker), log=worker.log, logger=worker._logger)


def _request(mi, plan, options=None):
    return PipelineExecutionRequest(pipeline='standard', input_path='source.mkv', output_path='out.mkv',
        container='mkv', media_info=mi, plan=plan, override={}, strip_only=False,
        duration_ms=1000, codec='h265', crf=23, preset='medium',
        encoder_options=options if options is not None else {'encoder': 'cpu'})


def _runner(commands, defaults=None):
    return StandardPipelineRunner(tools=NS(ffmpeg='ffmpeg'), codec='h265', crf=23,
        preset='medium', encoder_options=defaults or {},
        progress_runner=lambda cmd, *args: commands.append(cmd) or 0, subtitle_rules={})


@pytest.mark.parametrize('index', [0, 3])
def test_real_plan_with_global_video_index_reaches_standard_encoder(index):
    mi = _media(index)
    plan = _service().prepare_encode_plan('source.mkv', 'out.mkv', mi, 'standard', 'mkv', {})
    assert plan.vf_args[:2] == ['-map', f'0:{index}']
    commands = []
    result = _runner(commands).execute(_request(mi, plan))
    assert result.success, result.failure_reason
    assert commands[0][commands[0].index('-map') + 1] == f'0:{index}'


@pytest.mark.parametrize('maps', [['-map', '0:2'], ['-map', '0:3', '-map', '0:4'], ['-map', '0:v']])
def test_standard_rejects_wrong_additional_or_broad_video_maps(maps):
    commands = []
    plan = EncodePlan(None, [], ['-sn'], maps, ['-an'])
    result = _runner(commands).execute(_request(_media(), plan))
    assert not result.success
    assert commands == []


def test_explicit_empty_encoder_options_do_not_restore_global_gpu_settings():
    commands = []
    plan = EncodePlan(None, [], ['-sn'], ['-map', '0:v:0'], ['-an'])
    result = _runner(commands, {'encoder': 'nvenc', 'preset': 'p6'}).execute(_request(_media(), plan, {}))
    assert result.success
    assert commands[0][commands[0].index('-c:v') + 1] == 'libx265'


def test_logger_uses_same_empty_options_contract_as_executor():
    assert _runner([], {'encoder': 'nvenc'}).logger_start_params(encoder_options={})[0] == 'cpu'


def test_planning_does_not_mutate_service_defaults():
    options = {'encoder': 'cpu', 'nested': {'label': 'original'}}
    before = deepcopy(options)
    _service(options).prepare_encode_plan('source.mkv', 'out.mkv', _media(), 'standard', 'mkv', {})
    assert options == before


def test_plan_options_are_isolated_and_authoritative_for_execution():
    options = {'encoder': 'cpu', 'nested': {'label': 'original'}, 'autocrop_enabled': False}
    plan = _service().prepare_encode_plan('source.mkv', 'out.mkv', _media(), 'standard', 'mkv', {}, encoder_options=options)
    options['encoder'] = 'nvenc'
    options['nested']['label'] = 'changed'
    assert plan.encoder_options['nested']['label'] == 'original'
    commands = []
    assert _runner(commands).execute(_request(_media(), plan, options)).success
    assert commands[0][commands[0].index('-c:v') + 1] == 'libx265'


def test_explicit_empty_plan_options_do_not_inherit_service_autocrop_policy():
    calls = []
    service = _service({'autocrop_enabled': False}, lambda *args: calls.append(args) or None)
    service.prepare_encode_plan('source.mkv', 'out.mkv', _media(), 'standard', 'mkv', {}, encoder_options={})
    assert len(calls) == 1


def test_autocrop_probe_start_zero_is_preserved():
    calls = []
    _service({'autocrop_probe_start_s': 0}, lambda *args: calls.append(args) or None).prepare_encode_plan(
        'source.mkv', 'out.mkv', _media(), 'standard', 'mkv', {})
    assert calls[0][4] == 0


@pytest.mark.parametrize('encoder', ['cpu', 'nvenc', 'qsv', 'amf'])
@pytest.mark.parametrize('quality', ['23.0', None, float('inf')])
def test_quality_default_normalization_is_consistent_for_all_backends(encoder, quality):
    args = _vid_args('h265', quality, 'medium', {'encoder': encoder})
    flag = {'cpu': '-crf', 'nvenc': '-cq', 'qsv': '-global_quality', 'amf': '-qp_i'}[encoder]
    assert args[args.index(flag) + 1] == '23'


def test_strip_sidecar_failure_preserves_remux_and_partial_sidecars(monkeypatch):
    from dragontools.worker import converter_strip as module
    from dragontools.worker.workflow_pipeline_executor import WorkflowPipelineExecutor
    worker = NS(log=lambda *args: None)
    monkeypatch.setattr(module, 'build_strip_audio_args', lambda *args: ([], ['-an']))
    monkeypatch.setattr(module, 'build_strip_subtitle_args', lambda *args: ['-sn'])
    monkeypatch.setattr(module, 'run_strip_command', lambda *args, **kwargs: True)
    monkeypatch.setattr(module, 'export_strip_sidecars', lambda *args, **kwargs: (False, ['partial.de.srt']))
    helper = module.ConverterStripHelper(worker)
    temp = NS(reset_diagnostics=lambda: None, failure_reason='', failure_stage='', stderr='', last_tool='', last_command='')
    executor = WorkflowPipelineExecutor(standard_pipeline=None, strip_runner=helper.strip_only,
        dv_pipeline=None, hdrplus_pipeline=None, temp_state=temp)
    result = executor.execute(replace(_request(_media(), None), strip_only=True))
    assert not result.success
    assert result.preserve_failed_output
    assert result.sidecar_paths == ('partial.de.srt',)
    assert result.failure_stage == 'Untertitel-Export'


@pytest.mark.parametrize('code', [124, 130])
def test_standard_timeout_or_abort_never_starts_movtext_fallback(monkeypatch, code):
    runner = _runner([])
    runner._progress_runner = lambda *args: code
    calls = []
    monkeypatch.setattr(runner, '_try_mov_text_fallback', lambda **kwargs: calls.append(kwargs))
    plan = EncodePlan(None, [], ['-sn'], ['-map', '0:v:0'], ['-an'])
    assert not runner.execute(_request(_media(), plan)).success
    assert calls == []


def test_strip_unexpected_sidecar_error_preserves_finished_candidate(monkeypatch):
    from dragontools.worker import converter_strip as module
    from dragontools.worker.workflow_pipeline_executor import WorkflowPipelineExecutor
    monkeypatch.setattr(module, 'build_strip_audio_args', lambda *args: ([], ['-an']))
    monkeypatch.setattr(module, 'build_strip_subtitle_args', lambda *args: ['-sn'])
    monkeypatch.setattr(module, 'run_strip_command', lambda *args, **kwargs: True)
    def fail(*args, **kwargs):
        raise OSError('sidecar directory unavailable')
    monkeypatch.setattr(module, 'export_strip_sidecars', fail)
    helper = module.ConverterStripHelper(NS(log=lambda *args: None))
    temp = NS(reset_diagnostics=lambda: None, failure_reason='', failure_stage='', stderr='', last_tool='', last_command='')
    executor = WorkflowPipelineExecutor(standard_pipeline=None, strip_runner=helper.strip_only,
        dv_pipeline=None, hdrplus_pipeline=None, temp_state=temp)
    result = executor.execute(replace(_request(_media(), None), strip_only=True))
    assert not result.success
    assert result.preserve_failed_output
    assert 'sidecar directory unavailable' in result.failure_reason


def test_standard_unexpected_sidecar_error_preserves_finished_candidate(monkeypatch):
    runner = _runner([])
    runner._subtitle_rules = {'additional_sidecars_enabled': True}
    def fail(**kwargs):
        raise OSError('sidecar directory unavailable')
    monkeypatch.setattr(runner._subtitle_service, 'export_sidecars_result', fail)
    plan = EncodePlan(None, [], ['-sn'], ['-map', '0:v:0'], ['-an'])
    result = runner.execute(_request(_media(), plan))
    assert not result.success
    assert result.preserve_failed_output
    assert 'sidecar directory unavailable' in result.failure_reason


@pytest.mark.parametrize('code', [124, 130])
def test_strip_timeout_or_abort_never_starts_backup(monkeypatch, code):
    from dragontools.worker import converter_strip as module
    monkeypatch.setattr(module, 'build_strip_audio_args', lambda *args: ([], ['-an']))
    monkeypatch.setattr(module, 'build_strip_subtitle_args', lambda *args: ['-sn'])
    calls = []
    monkeypatch.setattr(module, 'retry_with_mov_text_backup', lambda *args, **kwargs: calls.append(kwargs) or NS(attempted=False, success=False, sidecar_paths=[]))
    worker = NS(log=lambda *args: None, tools=NS(ffmpeg='ffmpeg'),
        _progress=NS(run=lambda *args: code))
    assert not module.ConverterStripHelper(worker).strip_only('source.mkv', 'out.mkv', _media())
    assert calls == []
