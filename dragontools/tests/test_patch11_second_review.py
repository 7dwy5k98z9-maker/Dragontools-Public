"""Audio boundaries: semantic metadata, finite timing and owned outputs."""
from pathlib import Path
from types import SimpleNamespace as NS
import pytest

from dragontools.tests.test_review11_audio import _audio, _mapping, _rules
from dragontools.core.audio_sync_planner import AudioSyncPlanner, atempo_chain
from dragontools.core.audio_video_time_mapping import classify_time_mapping
from dragontools.core.audio_video_match_models import MatchPoint
from dragontools.rules.audio_plan import compute_audio_track_plan
from dragontools.worker.audio_mux_plan_service import AudioMuxPlanService
from dragontools.worker.converter_audio_args import build_audio_args


class Signal:
    def __init__(self):
        self.values = []
    def emit(self, *args):
        self.values.append(args)


@pytest.mark.parametrize('normal', [True, False])
def test_audio_metadata_preserves_forced_and_describes_actual_codec(monkeypatch, normal):
    stream = _audio(3, codec='dts', channels=6, bitrate=1500000, default=True)
    stream.forced = True
    plan = compute_audio_track_plan([stream], None, 'mkv', rules=_rules())
    if normal:
        import dragontools.worker.converter_audio_args as module
        monkeypatch.setattr(module, 'compute_audio_track_plan', lambda **kw: plan)
        logger = NS(audio=lambda *a, **kw: None, decision=lambda *a: None)
        args = build_audio_args(NS(_logger=logger), NS(audio_streams=[stream]), None, 'mkv')
    else:
        args = AudioMuxPlanService(tools=NS(ffmpeg='ffmpeg')).build_ffmpeg_cmd('source', 'out.mkv', plan)
    assert 'language=deu' in args
    assert 'title=Deutsch EAC3 5.1 640kbps' in args
    assert args[args.index('-disposition:a:0')+1] == 'default+forced'


def test_audio_mux_contract_checks_generated_title_and_forced(monkeypatch):
    import dragontools.worker.audio_mux_plan_service as module
    from dragontools.worker.output_contract_tracks import compare_audio_tracks
    stream = _audio(1, default=True)
    stream.forced = True
    plan = compute_audio_track_plan([stream], None, 'mkv', rules=_rules())
    monkeypatch.setattr(module, 'probe_output', lambda *a, **kw: NS(streams=({'codec_type':'video'},)))
    contract = AudioMuxPlanService(tools=NS(ffprobe='ffprobe')).build_expected_contract('source', NS(primary_video=None, video_streams=[object()], subtitle_streams=[]), plan)
    actual = {'codec_name':'aac', 'channels':2, 'tags':{'language':'deu','title':'wrong'}, 'disposition':{'default':1,'forced':0}}
    errors = compare_audio_tracks(contract, [actual])
    assert any('Titel' in e for e in errors)
    assert any('Forced' in e for e in errors)


@pytest.mark.parametrize('speed', [0, -1, float('nan')])
def test_invalid_tempo_is_rejected_instead_of_coerced(speed):
    with pytest.raises(ValueError):
        atempo_chain(speed)


@pytest.mark.parametrize('speed', [0, -1, float('nan')])
def test_invalid_mapping_cannot_create_enabled_audio_plan(speed):
    mapping = _mapping([_audio(1)])
    mapping.speed_factor = speed
    plan = AudioSyncPlanner().build_plan(mapping)
    assert plan.blocked and not plan.filter_graph


@pytest.mark.parametrize('index', [True, 1.8, '1.0', float('inf')])
def test_noninteger_audio_selection_never_selects_different_track(index):
    plan = AudioSyncPlanner().build_plan(_mapping([_audio(1)]), audio_stream_index=index)
    assert plan.blocked and plan.audio_stream_index == -1


def test_repeated_landmark_is_not_independent_evidence_for_sync():
    mapping = _mapping([_audio(1)])
    result = classify_time_mapping([MatchPoint(10, 10, .99, 99)] * 3,
        source_info=mapping.source_info, target_info=mapping.target_info)
    assert result.mode == 'D' and not result.can_process


def _job(monkeypatch, tmp_path, *, overwrite=True, failure=None):
    from dragontools.worker import audio_mux_job as module
    source = tmp_path / 'source.mkv'
    source.write_bytes(b'SOURCE')
    final = source if overwrite else tmp_path / 'final.mkv'
    legacy = tmp_path / 'legacy_stage.mkv'
    media = NS(video_streams=[object()], audio_streams=[_audio(1)], subtitle_streams=[], analysis_source='test', duration_s=10)
    monkeypatch.setattr(module, 'analyze_media', lambda *a: media)
    worker = NS(progress_file=Signal(), log_line=Signal(), file_result=Signal(), tools=NS(), overwrite_original=overwrite, abort_requested=False, abort_type='sofort')
    written = []
    def encode(cmd, *a):
        output = Path(cmd[-1]); output.write_bytes(b'VALID-MUX'); written.append(output)
        if failure == 'rc':
            return 7
        return 0
    worker.run_ffmpeg_with_progress = encode
    planner = NS(build_audio_plan=lambda mi: [], build_expected_contract=lambda *a: object(),
        build_output_path=lambda *a: (final, legacy if overwrite else None),
        build_ffmpeg_cmd=lambda src, out, plan: ['ffmpeg', '-n', '-i', src, out])
    verifier = NS(verify=lambda **kw: NS(ok=True, messages=[]))
    return module, module.AudioMuxJobRunner(worker, planner=planner, verifier=verifier), source, final, legacy, worker, written


def test_late_commit_failure_keeps_verified_mux_for_recovery(monkeypatch, tmp_path):
    module, runner, source, final, legacy, worker, written = _job(monkeypatch, tmp_path)
    def fail(**kw):
        raise OSError('locked destination')
    monkeypatch.setattr(module, 'commit_staged_output', fail)
    with pytest.raises(OSError):
        runner.run(str(source))
    assert source.read_bytes() == b'SOURCE'
    assert written[0].read_bytes() == b'VALID-MUX'


def test_mux_nonzero_returncode_cannot_commit_existing_output(monkeypatch, tmp_path):
    module, runner, source, final, legacy, worker, written = _job(monkeypatch, tmp_path, failure='rc')
    committed=[]
    monkeypatch.setattr(module, 'commit_staged_output', lambda **kw: committed.append(True))
    with pytest.raises(RuntimeError):
        runner.run(str(source))
    assert not committed and source.read_bytes() == b'SOURCE'


def test_output_collision_does_not_delete_other_job_file(monkeypatch, tmp_path):
    module, runner, source, final, legacy, worker, written = _job(monkeypatch, tmp_path, overwrite=False)
    def collide(cmd, *a):
        final.write_bytes(b'OTHER-JOB')
        if Path(cmd[-1]) == final:
            raise RuntimeError('ffmpeg -n refused existing target')
        Path(cmd[-1]).write_bytes(b'VALID-MUX')
        return 0
    worker.run_ffmpeg_with_progress=collide
    with pytest.raises((RuntimeError, OSError)):
        runner.run(str(source))
    assert final.read_bytes() == b'OTHER-JOB'


def test_start_does_not_replace_current_audio_worker(monkeypatch, qapp):
    import dragontools.gui.audio_muxer_widget as module
    widget=module.AudioMuxerWidget()
    current=object(); widget._worker=current
    widget._add_paths(['C:/movie.mkv'])
    calls=[]
    monkeypatch.setattr(module, 'AudioMuxThread', lambda **kw: calls.append(kw))
    widget._start()
    assert widget._worker is current and not calls
    widget._worker=None
    widget.close()


def test_aborted_zero_code_tool_is_not_success(monkeypatch, qapp):
    from dragontools.worker import audio_mux_thread as module
    from dragontools.worker.tool_runner import ToolRunResult
    monkeypatch.setattr(module, 'run_tool', lambda *a, **kw: ToolRunResult([], 0, aborted=True))
    worker=module.AudioMuxThread([])
    assert worker.run_ffmpeg_with_progress(['ffmpeg','out.mkv'], 10, 'source') == 130


def test_source_probe_failure_does_not_disable_auxiliary_preservation(monkeypatch):
    from dragontools.worker import audio_mux_plan_service as module
    def fail(*a, **kw):
        raise RuntimeError('source probe failed')
    monkeypatch.setattr(module, 'probe_output', fail)
    with pytest.raises(RuntimeError):
        module.AudioMuxPlanService(tools=NS(ffprobe='ffprobe')).build_expected_contract('source', NS(primary_video=None, video_streams=[object()], subtitle_streams=[]), [])


def test_late_finished_callback_does_not_clear_new_worker(qapp):
    from dragontools.gui.audio_muxer_widget import AudioMuxerWidget
    widget=AudioMuxerWidget()
    current=object(); widget._worker=current
    widget._on_finished(object())
    assert widget._worker is current
    widget._worker=None; widget.close()


@pytest.mark.parametrize('offset,speed', [(float('inf'),1), (0,float('inf'))])
def test_infinite_mapping_is_blocked_without_hanging(offset, speed):
    mapping=_mapping([_audio(1)])
    mapping.offset_s=offset; mapping.speed_factor=speed
    plan=AudioSyncPlanner().build_plan(mapping)
    assert plan.blocked and not plan.filter_graph


def _cut(start, end, source_start, source_end):
    from dragontools.core.audio_video_match_models import CutMatchResult, CutRegion
    return CutMatchResult(CutRegion(start,end), start,end,source_start,source_end,.99,.99)


@pytest.mark.parametrize('cuts', [
    [_cut(10,20,10,20),_cut(15,25,15,25)],
    [_cut(10,20,10,20),_cut(25,30,15,20)],
    [_cut(10,20,float('nan'),20)],
])
def test_invalid_cut_geometry_cannot_duplicate_or_reorder_audio(cuts):
    mapping=_mapping([_audio(1)]); mapping.mode='C'
    plan=AudioSyncPlanner().build_plan(mapping,cut_results=cuts)
    assert plan.blocked and not plan.filter_graph


def test_segmented_plan_keeps_leading_silence_for_negative_offset():
    mapping=_mapping([_audio(1)]); mapping.mode='C'; mapping.offset_s=-.5
    plan=AudioSyncPlanner().build_plan(mapping,cut_results=[_cut(10,12,9.5,11.5)])
    assert not plan.blocked
    assert plan.segments[0].target_start_s == .5
    assert 'adelay=500:all=1' in plan.filter_graph
