"""Constrained pairwise policy/track contracts, with controlled lifecycle I/O.

Native media read-back is covered separately. These cases deliberately inject
tool outcomes; they do not claim to encode every matrix row with native tools.
"""
from copy import deepcopy
from itertools import combinations
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from dragontools.core.models import AudioStream, MediaInfo, SubtitleStream, VideoStream
from dragontools.core.encoder_profile_override import effective_encoder_settings
from dragontools.core.rules_preview import build_rules_preview
from dragontools.gui.watch_folder_intake import apply_watch_profile_overrides
from dragontools.worker.live_queue_overrides import set_file_override
from dragontools.worker.pipeline_decision_service import PipelineDecisionService
from dragontools.worker.media_contract import build_expected_media_contract
from dragontools.worker.audio_metadata_args import audio_metadata_args
from dragontools.worker.converter_audio_args import build_audio_args
from dragontools.worker.converter_subtitle_args import build_subtitle_args
from dragontools.worker.workflow_output_commit import WorkflowOutputCommitCoordinator
from dragontools.worker.replace_service import ReplaceService
from dragontools.worker.mp4_remux_plan import MP4RemuxPlanner
from dragontools.worker.output_contract_tracks import compare_audio_tracks, compare_subtitle_tracks
from dragontools.worker.workflow_engine import ConversionWorkflowRunner
from dragontools.worker.workflow_models import PipelineExecutionRequest, PipelineExecutionResult
from dragontools.worker.workflow_pipeline_executor import WorkflowPipelineExecutor
from dragontools.worker.dv_runtime_models import DVTempState
from dragontools.rules.audio_plan import compute_audio_track_plan

MATRIX = json.loads((Path(__file__).parent/'fixtures/patch26_pipeline_matrix.json').read_text(encoding='utf-8'))
ROWS = MATRIX['cases']


def test_pairwise_matrix_covers_its_complete_valid_pair_universe():
    names = list(MATRIX['axes'])
    positions = list(combinations(range(len(names)), 2))
    def pairs(row):
        return {(i, row[names[i]], j, row[names[j]]) for i, j in positions}
    actual = set().union(*(pairs(row) for row in ROWS))
    # Counts are audited against the exhaustive constrained generator, and
    # every requested value must occur in actual executed cases.
    assert len(actual) == MATRIX['valid_pairs'] == MATRIX['covered_pairs']
    for name, values in MATRIX['axes'].items():
        assert {r[name] for r in ROWS} == set(values)


def _media(c, path):
    hdr = c['hdr'] != 'sdr'
    video = VideoStream(0, c['video'], 1920, 1080,
        hdr_format={'sdr': None, 'hdr10': 'hdr10', 'hdr10plus': 'hdr10plus', 'dv': 'dolby_vision'}[c['hdr']],
        bit_depth=10 if hdr else 8, color_transfer='smpte2084' if hdr else 'bt709',
        color_primaries='bt2020' if hdr else 'bt709',
        has_dolby_vision=c['hdr']=='dv', has_hdr10plus=c['hdr']=='hdr10plus')
    audio = AudioStream(7, 'deu', False, 'Quelle', c['audio'], c['channels'], bitrate=384000, default=True)
    subs = [] if c['subtitle']=='none' else [SubtitleStream(19, 'deu', False, 'Deutsch', c['subtitle'], default=False)]
    return MediaInfo(str(path), [audio], subs, [video], duration_s=2, is_hdr=hdr,
        dolby_vision=c['hdr']=='dv', dv_profile_major=8 if c['hdr']=='dv' else None,
        has_hdr10plus=c['hdr']=='hdr10plus')


def _settings(c):
    def value(key, default=None, type=None):
        from dragontools.core.settings_conversion import SET_KEY_OUTPUT_CONTAINER_STANDARD, SET_KEY_OUTPUT_CONTAINER_DV
        return c['output'] if key in {SET_KEY_OUTPUT_CONTAINER_STANDARD, SET_KEY_OUTPUT_CONTAINER_DV} else default
    return NS(value=value)


class _Log:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def _inputs(c, path):
    codec = {'h264': 'h264', 'hevc': 'h265', 'av1': 'av1'}[c['video']] if c['mode'] in {'strip','remux'} else 'h265'
    desired = {'encoder': 'cpu', 'preserve_dv': c['mode'] in {'dv','strip'},
        'preserve_hdrplus': c['mode'] in {'hdrplus','strip'},
        'sdr_hdr_enabled': c['mode']=='sdr_hdr', '_sdr_hdr_libplacebo_available': True}
    profile = {'key':'matrix26', 'label':'Matrix26', 'codec':codec, 'crf':21,
        'preset':'medium', 'scale':'original', 'encoder_options':deepcopy(desired)}
    base = desired if c['entry']=='default' else {**desired, 'preserve_dv':False, 'preserve_hdrplus':False}
    override = {'audio_mode':'custom', 'audio_tracks':[{'index':7,'mode':'auto'}],
        'subtitle_mode':'custom', 'subtitle_tracks':[] if c['subtitle']=='none' else [
            {'index':19,'keep':True,'burn_in':False}]}
    if c['mode']=='strip': override['processing_mode']='strip_only'
    if c['entry']=='profile': override['encoder_profile']=profile
    elif c['entry']=='per_file':
        override['encoder_override']={'codec':codec, 'encoder':'cpu', 'quality':21,
            'encoder_options':deepcopy(desired)}
    elif c['entry']=='watch':
        mapping = {str(path):override}
        apply_watch_profile_overrides(mapping, [str(path)], profile)
        override = mapping[str(path)]
    elif c['entry']=='queue':
        mapping = {}
        set_file_override(mapping, str(path), {**override, 'encoder_override':{
            'codec':codec, 'encoder':'cpu', 'quality':21, 'encoder_options':desired}})
        override = mapping[str(path)]
    return codec, base, override


@pytest.mark.parametrize('case', ROWS, ids=lambda c:c['id'])
def test_pairwise_pipeline_contract_and_lifecycle(case, tmp_path):
    c = case
    source = tmp_path / f'Quelle Ü.{c["source"]}'
    output = tmp_path / f'Ausgabe Ü.{c["output"]}'
    original = b'original-source' * 600
    candidate = b'candidate' * 600
    source.write_bytes(original)
    media = _media(c, source)
    codec, base, override = _inputs(c, source)
    rules = {'mp4_sidecars_enabled':False, 'pgs_original_storage':'internal_mkv',
        'burn_in_rules':{'auto_burn_forced':False}}
    effective = effective_encoder_settings(default_codec=codec, default_crf=23,
        default_preset='medium', default_scale_mode='original', default_encoder_options=base, file_override=override)
    preview = build_rules_preview(str(source), codec=codec, file_override=override, media_info=media,
        default_encoder_options=base, standard_container=c['output'], dv_container=c['output'],
        subtitle_rules=rules, planned_target=str(tmp_path/'Ziel Ü'))
    selector = PipelineDecisionService(codec=codec, encoder_options=base, file_overrides={},
        settings=_settings(c), logger=_Log())
    pipeline, container = selector.select_pipeline_context(str(source), media, override,
        effective_codec=effective['codec'], effective_encoder_options=effective['encoder_options'])
    assert (pipeline, container) == (preview['pipeline'], preview['target_container'])
    assert container == c['output']
    if c['mode']=='sdr_hdr':
        assert preview['sdr_hdr_requested'] and preview['sdr_hdr_applied']
    expected_pipeline = 'dv' if c['mode']=='dv' or (c['mode']=='strip' and c['hdr']=='dv') else (
        'hdrplus' if c['mode']=='hdrplus' or (c['mode']=='strip' and c['hdr']=='hdr10plus') else 'standard')
    assert pipeline == expected_pipeline
    assert preview['move']['planned_target'] == str(tmp_path/'Ziel Ü')
    contract = build_expected_media_contract(media_info=media, file_override=override, container=container,
        pipeline=pipeline, strip_only=c['mode']=='strip', effective_codec=codec,
        effective_preserve_hdrplus=c['mode'] in {'hdrplus','strip'}, subtitle_rules=rules,
        force_hdr_output=c['mode']=='sdr_hdr')
    assert contract.video_codec == (c['video'] if c['mode'] in {'strip','remux'} else 'hevc')
    assert contract.require_dolby_vision == (c['mode']=='dv' or c['mode']=='strip' and c['hdr']=='dv')
    assert contract.require_hdr10plus == (c['mode']=='hdrplus' or c['mode']=='strip' and c['hdr']=='hdr10plus')
    audio_plan = compute_audio_track_plan(audio_streams=media.audio_streams, file_override=override, container=container)
    args = build_audio_args(NS(_logger=_Log()), media, override, container)
    assert args[args.index('-map')+1] == '0:7'  # source stream ID is not output order
    actual_audio = []
    for decision in audio_plan:
        metadata = audio_metadata_args(decision)
        actual_audio.append({'codec_name':decision.target_codec, 'channels':decision.target_channels,
            'tags':{'language':'deu'},
            'disposition':{'default':1,'forced':0}})
        # The mux label is checked against emitted arguments, not copied from
        # ExpectedAudioTrack, so an omitted planned title is not a false oracle.
        actual_audio[-1]['tags']['title'] = next(v[6:] for v in metadata if v.startswith('title='))
    assert not compare_audio_tracks(contract, actual_audio)
    burn, sub_args = build_subtitle_args(NS(_logger=_Log(), log=lambda *a:None), str(source),
        media, override, container=container, subtitle_rules=rules)
    assert not burn
    expected_internal = c['subtitle']!='none' and not (
        container=='mp4' and c['subtitle'] in {'hdmv_pgs_subtitle','dvd_subtitle'})
    assert len(contract.subtitle_tracks) == int(expected_internal)
    actual_subs = []
    if expected_internal:
        assert sub_args[sub_args.index('-map')+1]=='0:19'
        expected_subcodec = 'mov_text' if container=='mp4' else (
            'subrip' if c['subtitle']=='mov_text' else c['subtitle'])
        assert contract.subtitle_tracks[0].codec == expected_subcodec
        actual_subs = [{'codec_name':expected_subcodec, 'tags':{'language':'deu'},
            'disposition':{'forced':0,'default':0}}]
    else:
        assert sub_args == ['-sn']
    assert not compare_subtitle_tracks(contract, actual_subs)
    if c['mode']=='remux':
        remux = MP4RemuxPlanner(ffmpeg_path='ffmpeg', apply_audio_rules=True, export_subtitles=True,
            ignore_subtitles=False, subtitle_rules=rules, faststart=True, log=lambda *a:None, log_audio=lambda *a,**kw:None)
        assert remux.video_compatibility(media)[0]
        remux_plan = remux.build(str(source), str(output), media)
        assert remux_plan.expected_contract.container == container
        assert remux_plan.expected_contract.video_codec == c['video']
        remux_plan.workspace.__exit__(None, None, None)
    calls = []
    aborted = {'value':False}
    class Pipeline:
        def execute(self, request):
            calls.append(('pipeline', request.container, request.input_path))
            if c['outcome']=='tool_error':
                return PipelineExecutionResult(success=False, failure_stage='Tool', failure_reason='injected rc=1')
            output.write_bytes(candidate)
            return PipelineExecutionResult.succeeded()
    executor = WorkflowPipelineExecutor(standard_pipeline=Pipeline(), dv_pipeline=Pipeline(), hdrplus_pipeline=Pipeline(),
        strip_runner=lambda *a: bool(Pipeline().execute(NoneRequest).success), temp_state=DVTempState())
    NoneRequest = NS(container=container, input_path=str(source))
    commit = WorkflowOutputCommitCoordinator(
        replace_service=ReplaceService(overwrite_original=True, log=lambda *a:None,
            journal_root=tmp_path/'journal', abort_check=lambda:aborted['value']),
        logger=_Log(), result_service=NS(), sidecar_outputs={}, postprocess_outputs={},
        abort_check=lambda:aborted['value'])
    class Services:
        def analyze(self, ctx): ctx.analysis=media
        def build_plan(self, ctx, ov):
            ctx.pipeline, ctx.container, ctx.output_path=pipeline, container, str(output)
            ctx.effective_codec, ctx.effective_crf, ctx.effective_preset=codec, 21, 'medium'
            ctx.effective_encoder_options=effective['encoder_options']; ctx.strip_only=c['mode']=='strip'
        def process(self, ctx, ov):
            result = executor.execute(PipelineExecutionRequest.from_context(ctx, ov))
            if not result.success: raise RuntimeError(result.failure_reason)
            if c['outcome'] in {'cancel','shutdown'}: aborted['value']=True
        def verify(self, ctx):
            observed = deepcopy(actual_audio)
            if c['outcome']=='verify_error': observed[0]['channels']=99
            errors = compare_audio_tracks(contract, observed)
            errors += compare_subtitle_tracks(contract, actual_subs)
            if errors: raise RuntimeError('; '.join(errors))
            calls.append(('verified',container))
        def replace(self, ctx):
            assert ('verified',container) in calls
            commit.replace(ctx)
            calls.append(('commit',container))
        def finalize(self, ctx): calls.append(('finalize',container))
        def fail(self, ctx, error, traceback): calls.append(('failure',error))
        def cleanup(self, ctx): calls.append(('cleanup',container))
    ok = ConversionWorkflowRunner(Services(), replace_original=True).run(str(source), override)
    assert ok is (c['outcome']=='success')
    assert sum(call[0]=='commit' for call in calls) == int(ok)
    assert sum(call[0]=='finalize' for call in calls) == int(ok)
    assert sum(call[0]=='cleanup' for call in calls) == 1
    if ok:
        final = source.with_suffix('.'+container)
        assert final.read_bytes()==candidate
        if final!=source: assert not source.exists()
    else:
        assert source.read_bytes()==original
        if c['outcome']!='tool_error': assert output.read_bytes()==candidate
