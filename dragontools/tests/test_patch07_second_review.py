from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from dragontools.tests.test_dv_corrupt_rpu_fallback import _ctx, _services
from dragontools.tests.test_review07_dolby_vision_core import _encoder, _video_service
from dragontools.worker.dv_crop_reconcile import read_level5_offsets
from dragontools.worker.dv_encode_command import build_dv_encode_command
from dragontools.worker.dv_level5_editor import DVLevel5Editor
from dragontools.worker.dv_pipeline_context import DVWorkFiles
from dragontools.worker.dv_rpu_service import DVRpuService
from dragontools.worker.frame_count_evidence import FrameCountEvidence, temporal_mapping_for_filters
from dragontools.worker.workflow_models import PipelineExecutionResult


def _zero():
    return dict(left=0, right=0, top=0, bottom=0)


@pytest.mark.parametrize('bad', [0.5, -0.5, True, 'garbage', None, -1])
def test_level5_editor_rejects_one_invalid_preset_among_zero_offsets(tmp_path, bad):
    payload = {'active_area': {'presets': [_zero(), {**_zero(), 'top': bad}]}}
    editor = DVLevel5Editor(dovi_tool_path='dovi_tool', log=lambda *_: None)
    def run(command, **kwargs):
        Path(command[-1].split('=', 1)[1]).write_text(json.dumps(payload), encoding='utf-8')
        return 0
    assert not editor._verify_zero_level5(run, rpu_final=tmp_path / 'rpu', export_json=tmp_path / 'l5.json')


def test_level5_partial_preset_cannot_be_ignored(tmp_path):
    p = tmp_path / 'l5.json'
    p.write_text(json.dumps({'presets': [_zero(), {'left': 8, 'top': 0}]}), encoding='utf-8')
    with pytest.raises(ValueError):
        read_level5_offsets(p)


def test_level5_bom_is_valid_for_all_consumers(tmp_path):
    p = tmp_path / 'l5.json'
    p.write_text(json.dumps({'presets': [_zero()]}), encoding='utf-8-sig')
    assert read_level5_offsets(p) == ((0, 0, 0, 0),)


def test_editor_integer_failure_cannot_reuse_stale_rpu(tmp_path):
    original, final = tmp_path / 'source.rpu', tmp_path / 'final.rpu'
    original.write_bytes(b'original')
    final.write_bytes(b'stale')
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        if 'editor' in command:
            return 1
        Path(command[-1].split('=', 1)[1]).write_text(json.dumps({'presets': [_zero()]}))
        return 0
    editor = DVLevel5Editor(dovi_tool_path='dovi_tool', log=lambda *_: None)
    assert editor.resolve_rpu_for_crop(run, crop='crop=128:64:0:4',
        media_info=SimpleNamespace(primary_video=SimpleNamespace(width=128, height=72)),
        rpu_orig=original, rpu_final=final, edit_json=tmp_path / 'edit.json',
        save_failure_artifacts=lambda *_: tmp_path) is None
    assert len(calls) == 1


@pytest.mark.parametrize('rc', [124, 130])
def test_level5_verification_does_not_retry_timeout_or_cancel(tmp_path, rc):
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        if len(calls) == 1:
            return rc
        Path(command[-1].split('=', 1)[1]).write_text(json.dumps({'presets': [_zero()]}))
        return 0
    editor = DVLevel5Editor(dovi_tool_path='dovi_tool', log=lambda *_: None)
    assert not editor._verify_zero_level5(run, rpu_final=tmp_path / 'rpu', export_json=tmp_path / 'l5.json')
    assert len(calls) == 1


def _failure(**kwargs):
    fields = dict(success=False, failure_stage='STEP 3/7 RPU-Extraktion',
        failure_reason='dovi_tool failed (rc=1)', tool='dovi_tool.exe',
        command='dovi_tool.exe -m 2 extract-rpu -i in.mkv',
        tool_output='Error: Invalid RPU last byte: 248')
    fields.update(kwargs)
    return PipelineExecutionResult(**fields)


def test_current_track_error_cannot_borrow_stale_parser_signature():
    svc, temp, _, planning, executor = _services(_failure(tool_output='Error: No track found for ID 0'), PipelineExecutionResult.succeeded())
    temp.stderr = 'Error: Invalid RPU last byte: 248'
    with pytest.raises(RuntimeError):
        svc.process(_ctx(), {})
    assert not planning.overrides and len(executor.requests) == 1


@pytest.mark.parametrize('reason', ['STEP 3/7 RPU-Extraktion: durch Benutzer abgebrochen', 'STEP 3/7 RPU-Extraktion: Timeout nach 3600s'])
def test_corrupt_signature_during_cancel_or_timeout_never_replans(reason):
    svc, _, _, planning, executor = _services(_failure(failure_reason=reason), PipelineExecutionResult.succeeded())
    with pytest.raises(RuntimeError):
        svc.process(_ctx(), {})
    assert not planning.overrides and len(executor.requests) == 1


@pytest.mark.parametrize('stage,command', [('STEP 6/7 RPU-Extraktion Nachprüfung', 'dovi_tool.exe extract-rpu'), ('STEP 3/7 RPU-Extraktion', 'dovi_tool.exe inject-rpu')])
def test_fallback_requires_exact_source_stage_and_extraction_command(stage, command):
    svc, _, _, planning, executor = _services(_failure(failure_stage=stage, command=command), PipelineExecutionResult.succeeded())
    with pytest.raises(RuntimeError):
        svc.process(_ctx(), {})
    assert not planning.overrides and len(executor.requests) == 1


@pytest.mark.parametrize('profile', [5, 7, 8])
def test_dv_filter_conversion_targets_global_video_input_before_two_input_overlay(tmp_path, profile):
    args = ['-filter_complex', '[0:3][0:4]overlay[out]', '-map', '[out]']
    plan = build_dv_encode_command(ffmpeg_path='ffmpeg', encoder_config=_encoder(), input_path='input.mkv',
        output_hevc=tmp_path / 'out.hevc', vf_args=args, profile_major=profile, source_stream_index=3)
    graph = plan.command[plan.command.index('-filter_complex') + 1]
    assert graph.startswith('[0:3]libplacebo=' if profile == 5 else '[0:3]format=')
    assert ';' in graph and '[0:4]overlay' in graph
    assert '[out],format=' not in graph
    if profile != 5:
        assert graph.count('setparams=') == 2
    assert [plan.command[i+1] for i, s in enumerate(plan.command) if s == '-map'] == ['[out]']
    assert args[1] == '[0:3][0:4]overlay[out]'


@pytest.mark.parametrize('value', [True, 1.8, '7.1', 0, -1])
def test_rpu_service_rejects_non_tracknumber_before_tool_call(tmp_path, value):
    calls = []
    service = DVRpuService(dovi_tool_path='dovi_tool', log=lambda *_: None)
    with pytest.raises(ValueError):
        service.extract_rpu(lambda cmd: calls.append(cmd) or 0, input_path='movie.mkv', output_rpu=tmp_path / 'out', track_number=value)
    assert not calls


@pytest.mark.parametrize('payload', [[], {'tracks': {}}, {'tracks': [{'type': 'video', 'properties': {'number': 1.8}}, {'type': 'video', 'properties': {'number': 9}}]}, {'tracks': [{'type': 'video', 'properties': {'number': 7}}]}])
def test_matroska_identification_is_strict_and_topology_must_agree(tmp_path, payload):
    v0, v1 = SimpleNamespace(index=1), SimpleNamespace(index=3)
    state = SimpleNamespace(request=SimpleNamespace(input_path='multi.mkv', media_info=SimpleNamespace(primary_video=v0, video_streams=[v0, v1])))
    service = _video_service(tmp_path, rpu_service=None)
    runner = SimpleNamespace(run=lambda *_a, **_kw: SimpleNamespace(returncode=0, stdout=json.dumps(payload)))
    assert service._resolve_matroska_track_number(state, runner) is None
    assert service._temp_state.failure_reason


@pytest.mark.parametrize('count', [True, 1.5, '1.5'])
def test_exact_frame_evidence_does_not_round_or_accept_boolean(tmp_path, count):
    with pytest.raises(ValueError):
        FrameCountEvidence.reliable(count, source='test', path=tmp_path / 'x', stage='test')


def test_metadata_injection_cannot_revive_stale_input_evidence(tmp_path):
    original, output = tmp_path / 'original', tmp_path / 'output'
    original.write_bytes(b'initial')
    evidence = FrameCountEvidence.reliable(10, source='encode', path=original, stage='encode', temporal_mapping='preserved')
    original.write_bytes(b'a replacement containing different frames')
    output.write_bytes(b'injected replacement')
    derived = evidence.derive_for_metadata_only_output(output, source='inject', stage='inject')
    assert derived.reliability == 'unknown' and derived.count is None


@pytest.mark.parametrize('chain', ['reverse', 'tpad=stop=5', 'trim=start=1', 'shuffleframes=1 0', 'loop=loop=2:size=10', 'bwdif=mode=send_field'])
def test_additional_timeline_filters_do_not_claim_preserved_mapping(chain):
    assert temporal_mapping_for_filters(['-vf', chain]) == 'changed'


def test_real_runner_timeout_cannot_become_a_second_editor_export(monkeypatch, tmp_path):
    from dragontools.worker.dv_command_runner import DVCommandRunner
    from dragontools.worker.dv_runtime_models import DVTempState
    from dragontools.worker.tool_runner import ToolRunResult
    calls = []
    def fake_tool(command, **kwargs):
        calls.append(command)
        if len(calls) == 1:
            return ToolRunResult(command=list(command), returncode=124, timed_out=True)
        Path(command[-1].split('=', 1)[1]).write_text(json.dumps({'presets': [_zero()]}))
        return ToolRunResult(command=list(command), returncode=0)
    monkeypatch.setattr('dragontools.worker.dv_command_runner.run_tool', fake_tool)
    runner = DVCommandRunner(log=lambda *_: None, verbose_log=lambda *_: None, no_window_kwargs=lambda: {}, temp_state=DVTempState())
    editor = DVLevel5Editor(dovi_tool_path='dovi_tool', log=lambda *_: None)
    assert not editor._verify_zero_level5(runner.run, rpu_final=tmp_path / 'rpu', export_json=tmp_path / 'l5.json')
    assert len(calls) == 1


def test_completed_recovery_result_survives_logger_failure(tmp_path):
    from dragontools.worker.dv_failure_recovery import preserve_completed_dv_work
    from dragontools.worker.dv_pipeline_context import DVPipelineResult, DVPipelineState, DVRunRequest
    from dragontools.worker.dv_runtime_models import DVTempState
    work = tmp_path / 'dv'
    work.mkdir()
    files = DVWorkFiles.create(work)
    files.enc_hevc.write_bytes(b'completed encode')
    req = DVRunRequest.create(input_path=str(tmp_path / 'source.mkv'), output_path=str(tmp_path / 'out.mkv'), media_info=SimpleNamespace(),
        vf_args=[], audio_args=[], audio_input_args=[], sn=[], crop=None, override={}, preserve_hdrplus=False, container='mkv')
    state = DVPipelineState(request=req, files=files, video_encode_completed=True)
    def broken_log(*args):
        raise RuntimeError('logger gone')
    result = preserve_completed_dv_work(state, DVPipelineResult(False, failure_stage='injection'), log=broken_log)
    assert result.preserve_failed_output and result.failure_archive_path
    assert (Path(result.failure_archive_path) / 'encoded.hevc').read_bytes() == b'completed encode'


def test_crop_failure_archives_are_unique_and_accept_integer_tool_result(monkeypatch, tmp_path):
    from datetime import datetime
    from dragontools.worker.dv_failure_recovery import DVFailureRecovery
    class FixedTime:
        @staticmethod
        def now():
            return datetime(2026, 10, 6, 1, 2, 3)
    monkeypatch.setattr('dragontools.worker.dv_failure_recovery.datetime', FixedTime)
    rpu = tmp_path / 'source.rpu'
    rpu.write_bytes(b'first')
    svc = DVFailureRecovery(log=lambda *_: None)
    def save():
        return svc.save_dv_crop_failure(input_path=str(tmp_path / 'source.mkv'), output_path=str(tmp_path / 'out.mkv'), crop='crop=128:64:0:4',
            plain_mp4=tmp_path / 'absent', src_hevc=tmp_path / 'absent2', enc_hevc=tmp_path / 'absent3',
            rpu_orig=rpu, rpu_final=tmp_path / 'absent4', edit_json=tmp_path / 'absent5', audio_tracks=[],
            mux_plain_mp4_without_dv=lambda: False, level5_proc=1)
    first = save()
    rpu.write_bytes(b'second')
    second = save()
    assert first != second and (first / 'rpu_extracted.bin').read_bytes() == b'first'
    assert (second / 'rpu_extracted.bin').read_bytes() == b'second'
    assert 'MP4 ohne DV wurde gesichert' not in (second / 'status.txt').read_text(encoding='utf-8')


def test_partial_repair_does_not_decode_temporally_changed_source(tmp_path, monkeypatch):
    from dragontools.tests.test_dv_partial_frame_repair import _cfg
    from dragontools.worker.dv_partial_frame_repair import DVPartialFrameRepair
    request = SimpleNamespace(input_path='source.mkv', profile_major=8, vf_args=['-vf', 'reverse'])
    state = SimpleNamespace(request=request, files=DVWorkFiles.create(tmp_path), effective_vf_args=request.vf_args)
    repair = DVPartialFrameRepair(tools=SimpleNamespace(ffmpeg='ffmpeg'), encoder_config=_cfg(), progress_runner=None,
        log=lambda *_: None, verbose_log=lambda *_: None)
    calls = []
    monkeypatch.setattr(repair, '_write_fingerprint', lambda *_a, **_kw: calls.append(True) or False)
    assert not repair.attempt(state=state, runner=None, expected_rpu_frames=100, actual_encode_frames=99)
    assert not calls


@pytest.mark.parametrize('frames', [10000, 120])
def test_partial_repair_refuses_unbounded_or_full_movie_window(frames):
    from dragontools.worker.dv_partial_frame_repair import GapRegion, choose_repair_window
    region = GapRegion(encoded_start=0, encoded_end=frames, delta=1, observations=20)
    assert choose_repair_window(region=region, irap_points=[], encoded_frames=frames, encoded_size=1000) is None


def test_dv5_bridge_inherits_pending_abort_and_pause_before_child_run(monkeypatch):
    from unittest.mock import MagicMock
    from dragontools.worker import dv5_encode_fallback as module
    from dragontools.worker.converter_config import ConverterConfig
    from dragontools.tests.test_dv_corrupt_rpu_fallback import _Logger
    captured = []
    class Child:
        erfolgreich = 0
        fehlgeschlagen = 1
        def __init__(self, *args, **kwargs):
            self.file_progress = MagicMock()
            self.file_result = MagicMock()
            self.worker_event = MagicMock()
            self.aborted = None
            self.paused = False
        def request_abort(self, mode):
            self.aborted = mode
        def pause(self):
            self.paused = True
        def run(self):
            captured.append((self.aborted, self.paused))
    monkeypatch.setattr(module, 'ConverterThread', Child)
    worker = SimpleNamespace(file_overrides={}, _logger=_Logger(), log=lambda *_: None, file_progress=MagicMock(), file_result=MagicMock(),
        worker_event=MagicMock(), abort_requested=True, abort_type='sofort', _paused=True)
    config = ConverterConfig(codec='h265', crf=22, preset='medium', scale_mode='original', encoder_options={}, overwrite_original=False)
    assert not module.DV5EncodeFallbackRunner(worker, config).run('source.mkv')
    assert captured == [('sofort', True)]
    assert worker._active_fallback_worker is None


@pytest.mark.parametrize('hdrplus', [False, True])
@pytest.mark.parametrize('profile', [5, 7, 8])
def test_corrupt_retry_uses_real_planning_profile_and_pipeline_policy(hdrplus, profile):
    from unittest.mock import MagicMock
    from dragontools.tests.test_patch05_second_review import _media, _service
    from dragontools.worker.pipeline_decision_service import PipelineDecisionService
    from dragontools.worker.workflow_planning_service import WorkflowPlanningService
    from dragontools.worker.workflow_models import WorkflowConfig
    svc, _, logger, _, executor = _services(_failure(), PipelineExecutionResult.succeeded(verified_hdr10plus=hdrplus))
    config = WorkflowConfig(codec='h265', crf=22, preset='medium', scale_mode='original',
        encoder_options={'encoder': 'cpu', 'preserve_dv': True, 'preserve_hdrplus': True}, strip_only=False, subtitle_rules={})
    decision = PipelineDecisionService(codec='h265', encoder_options=config.encoder_options, file_overrides={},
        settings=SimpleNamespace(value=lambda key, default=None, **kwargs: default), logger=logger)
    planning = WorkflowPlanningService(config=config, runtime_state=SimpleNamespace(current_idx=1, total_count=1), logger=MagicMock(),
        pipeline_decision=decision, encode_plan=_service(), standard_pipeline=SimpleNamespace(logger_start_params=lambda **kwargs: ('cpu', 22, 'CRF', 'medium')),
        output_paths=SimpleNamespace(resolve_output_path=lambda path, container, **kwargs: (Path('.'), 'out.' + container)))
    svc._planning = planning
    ctx = _ctx(has_hdrplus=hdrplus, preserve_hdrplus=True)
    ctx.analysis = _media()
    ctx.analysis.dolby_vision = True
    ctx.analysis.dv_profile_major = profile
    ctx.analysis.has_hdr10plus = hdrplus
    override = {'encoder_profile': {'codec': 'h265', 'encoder_options': {'preserve_dv': True, 'preserve_hdrplus': True}}}
    planning.build_plan(ctx, override)
    assert ctx.pipeline == 'dv'
    svc.process(ctx, override)
    assert [r.pipeline for r in executor.requests] == ['dv', 'hdrplus' if hdrplus else 'standard']
    # These resolved policy fields include source capabilities. Encoder profile
    # preferences remain stored independently; the explicit retry wins.
    assert executor.requests[-1].preserve_hdrplus is hdrplus
    assert executor.requests[-1].override['preserve_dv'] is False
    assert ctx.effective_preserve_dv is False
    assert override['encoder_profile']['encoder_options']['preserve_dv'] is True
    assert ctx.expected_media_contract.video_stream_count == 1
    if profile == 5:
        assert 'libplacebo=' in str(ctx.plan.vf_args)


def test_failed_retry_does_not_start_a_third_pipeline():
    svc, _, _, planning, executor = _services(_failure(), _failure())
    with pytest.raises(RuntimeError):
        svc.process(_ctx(), {})
    assert len(planning.overrides) == 1 and len(executor.requests) == 2


@pytest.mark.parametrize('rc', [124, 130])
def test_crop_diagnostic_timeout_or_abort_stops_without_retry(tmp_path, rc):
    from dragontools.worker.dv_crop_reconcile import reconcile_dv_crop
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return rc
    outcome = reconcile_dv_crop(runner=SimpleNamespace(run=run), dovi_tool='dovi_tool', rpu_path=tmp_path / 'rpu', export_path=tmp_path / 'l5',
        source_width=128, source_height=72, autocrop_text=None, input_path='source.mkv')
    assert not outcome.success and not outcome.disable_dv
    assert len(calls) == 1


@pytest.mark.parametrize('policy', [False, True])
def test_dv5_bridge_keeps_global_hdr10plus_policy(monkeypatch, policy):
    from unittest.mock import MagicMock
    from dragontools.worker import dv5_encode_fallback as module
    from dragontools.worker.converter_config import ConverterConfig
    options = []
    class Child:
        erfolgreich = 1
        fehlgeschlagen = 0
        def __init__(self, files, config, **kwargs):
            options.append(config.encoder_options)
            self.file_progress, self.file_result, self.worker_event = MagicMock(), MagicMock(), MagicMock()
        def run(self):
            pass
    monkeypatch.setattr(module, 'ConverterThread', Child)
    worker = SimpleNamespace(file_overrides={}, _logger=MagicMock(), log=lambda *_: None,
        file_progress=MagicMock(), file_result=MagicMock(), worker_event=MagicMock())
    config = ConverterConfig(codec='h265', crf=22, preset='medium', scale_mode='original', overwrite_original=False,
        encoder_options={'preserve_dv': False, 'preserve_hdrplus': policy})
    assert module.DV5EncodeFallbackRunner(worker, config).run('source.mkv')
    assert options[0]['preserve_hdrplus'] is policy
    assert options[0]['preserve_dv'] is True
    assert config.encoder_options['preserve_dv'] is False


@pytest.mark.parametrize('index', [True, 1.5])
def test_dv_preflight_rejects_non_discrete_stream_indices(tmp_path, index):
    from dragontools.tests.test_review07_dolby_vision_core import _preflight, _request
    video = SimpleNamespace(index=index, codec='hevc')
    media = SimpleNamespace(primary_video=video, video_streams=[video], dv_profile_major=8, ffmpeg_stream_indices_trusted=True)
    ok, _, _ = _preflight().validate(encoder_config=_encoder(), request=_request(tmp_path, media_info=media))
    assert not ok


def test_mkvmerge_warning_identification_is_semantically_validated(tmp_path):
    first, second = SimpleNamespace(index=1), SimpleNamespace(index=3)
    state = SimpleNamespace(request=SimpleNamespace(input_path='multi.mkv', media_info=SimpleNamespace(primary_video=second, video_streams=[first, second])))
    payload = {'tracks': [{'type': 'video', 'properties': {'number': 2}}, {'type': 'video', 'properties': {'number': 7}}]}
    runner = SimpleNamespace(run=lambda *_a, **_kw: SimpleNamespace(returncode=1, stdout=json.dumps(payload)))
    assert _video_service(tmp_path, rpu_service=None)._resolve_matroska_track_number(state, runner) == 7


@pytest.mark.parametrize('rc', [124, 130])
def test_final_level5_optional_diagnostic_does_not_retry_terminal_status(tmp_path, rc):
    from dragontools.tests.test_review07_dolby_vision_core import _final_verifier
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return rc
    state = SimpleNamespace(files=SimpleNamespace(root=tmp_path), final_rpu_level5_offsets=())
    _final_verifier(tmp_path)._capture_final_level5(state, tmp_path / 'rpu', SimpleNamespace(run=run))
    assert len(calls) == 1
    assert state.final_rpu_level5_offsets == ()


def test_recovery_cleanup_veto_is_installed_before_archive_logging(tmp_path):
    from dragontools.worker.cleanup_service import CleanupService
    source, output, subtitle = tmp_path / 'source.mkv', tmp_path / 'out.mkv', tmp_path / 'out.de.srt'
    source.write_bytes(b'original')
    output.write_bytes(b'completed candidate')
    subtitle.write_bytes(b'completed subtitle')
    result = PipelineExecutionResult(success=False, sidecar_paths=(str(subtitle),),
        failure_archive_path=str(tmp_path / 'Archiv'), preserve_failed_output=True)
    svc, _, _, _, _ = _services(result)
    svc._output_commit = object()
    svc._cleanup_service = CleanupService(overwrite_original=False, temp_overwrite_dir=lambda base: base / 'temp', log=lambda *_: None)
    def broken_log(*args):
        raise RuntimeError('archive logger unavailable')
    svc._logger.warn = broken_log
    ctx = _ctx()
    ctx.input_path, ctx.output_path = str(source), str(output)
    ctx.base_dir, ctx.success, ctx.keep_failed_output = tmp_path, False, False
    try:
        svc._apply_pipeline_result_state(ctx, result)
    except RuntimeError:
        pass
    finally:
        svc.cleanup(ctx)
    assert source.read_bytes() == b'original'
    assert output.read_bytes() == b'completed candidate'
    assert subtitle.read_bytes() == b'completed subtitle'
    assert ctx.keep_failed_output
