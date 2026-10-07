"""Utility transactions retain the source, verified work and exact title choice."""
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from dragontools.tests.test_review17_iso_merge_remux import _Signal, _Logger


@pytest.fixture(autouse=True)
def isolate_replace_journals(tmp_path, monkeypatch):
    from dragontools.core.output_replace import commit_staged_output
    from dragontools.worker import mp4_remux_file_service as module
    monkeypatch.setattr(module, 'commit_staged_output', partial(commit_staged_output, journal_root=tmp_path / 'journals'))


def _mp4_job(tmp_path, *, run, verifier=True, source=None):
    from dragontools.worker.mp4_remux_file_service import MP4RemuxFileService
    from dragontools.worker.mp4_remux_plan import MP4RemuxPlan
    source = source or tmp_path / 'source.mp4'
    source.write_bytes(b'ORIGINAL')
    staging = tmp_path / 'owned_stage.mp4'
    destination = source
    plan = MP4RemuxPlan(source, destination, staging, ('ffmpeg', str(staging)), 10, (), 0, 0)
    results = []
    planner = SimpleNamespace(build=lambda *_: plan, video_compatibility=lambda _: (True, 'h264'))
    service = MP4RemuxFileService(planner=planner, logger=_Logger(), log=lambda *a: None,
        run_ffmpeg=run, export_sidecars=lambda *a, **kw: None,
        commit_sidecars=lambda *a, **kw: None, cleanup_sidecars=lambda _: None,
        abort_requested=lambda: False, emit_file_result=lambda *a: results.append(a),
        emit_file_progress=lambda *a: None, export_subtitles=False, ignore_subtitles=True,
        output_verifier=SimpleNamespace(verify=lambda **kw: SimpleNamespace(ok=True, messages=())) if verifier else None)
    media = SimpleNamespace(analysis_warnings=[], analysis_source='test')
    return service, source, staging, results, media


@pytest.mark.parametrize('return_code', [1, 130, None, True])
def test_mp4_rejects_unsuccessful_adapter_even_if_it_left_a_file(tmp_path, return_code):
    def run(cmd, *_):
        Path(cmd[-1]).write_bytes(b'REMUX')
        return return_code
    service, source, stage, results, media = _mp4_job(tmp_path, run=run)
    assert not service.remux(str(source), str(source), media,
        current_index=1, total_files=1, user_abort_error=RuntimeError)
    assert source.read_bytes() == b'ORIGINAL'
    assert results[-1][1] is False


def test_mp4_missing_verifier_cannot_authorize_source_replacement(tmp_path):
    def run(cmd, *_):
        Path(cmd[-1]).write_bytes(b'NOT A VALID MP4')
        return 0
    service, source, stage, results, media = _mp4_job(tmp_path, run=run, verifier=False)
    assert not service.remux(str(source), str(source), media,
        current_index=1, total_files=1, user_abort_error=RuntimeError)
    assert source.read_bytes() == b'ORIGINAL'


def test_mp4_source_replaced_during_tool_execution_is_preserved(tmp_path, monkeypatch):
    from dragontools.core.output_replace import commit_staged_output
    from dragontools.worker import mp4_remux_file_service as module
    monkeypatch.setattr(module, 'commit_staged_output', partial(commit_staged_output, journal_root=tmp_path / 'journals'))
    def run(cmd, *_):
        source.unlink()
        source.write_bytes(b'FOREIGN REPLACEMENT')
        Path(cmd[-1]).write_bytes(b'REMUX OF OLD SOURCE')
        return 0
    service, source, stage, results, media = _mp4_job(tmp_path, run=run)
    assert not service.remux(str(source), str(source), media,
        current_index=1, total_files=1, user_abort_error=RuntimeError)
    assert source.read_bytes() == b'FOREIGN REPLACEMENT'


def _makemkv_service(tmp_path, monkeypatch, *, verify=None, abort=False):
    from dragontools.worker import iso_makemkv_service as module
    worker = SimpleNamespace(abort_requested=abort, abort_type='sofort')
    verifier = Mock()
    verifier.verify.side_effect = verify or (lambda *a, **kw: SimpleNamespace(ok=True, messages=()))
    monkeypatch.setattr(module, 'OutputVerifier', lambda **kw: verifier)
    service = module.ISOMakeMKVService(tools=SimpleNamespace(ffprobe='ffprobe'),
        inspector=SimpleNamespace(makemkv_source=lambda path: f'iso:{path}'), worker=worker,
        log=lambda *a: None, progress=lambda *a: None)
    def run(args, progress_path=None):
        (Path(args[-1]) / f'title{int(args[-2]):02d}.mkv').write_bytes(b'MEDIA' * 512)
        return 0, []
    return service, worker, run


def test_makemkv_abort_during_verification_never_publishes(tmp_path, monkeypatch):
    def verify(*a, **kw):
        worker.abort_requested = True
        return SimpleNamespace(ok=True, messages=())
    service, worker, run = _makemkv_service(tmp_path, monkeypatch, verify=verify)
    result = service.extract_titles('disc.iso', [1], str(tmp_path), run_makemkv=run)
    assert not result.ok
    assert not (tmp_path / 'title01.mkv').exists()


def test_makemkv_verified_media_survives_destination_collision(tmp_path, monkeypatch):
    service, _, run = _makemkv_service(tmp_path, monkeypatch)
    (tmp_path / 'title01.mkv').write_bytes(b'EXISTING')
    result = service.extract_titles('disc.iso', [1], str(tmp_path), run_makemkv=run)
    assert not result.ok
    assert (tmp_path / 'title01.mkv').read_bytes() == b'EXISTING'
    assert any(path.read_bytes() == b'MEDIA' * 512 for path in tmp_path.rglob('*.mkv') if path.parent != tmp_path)


@pytest.mark.parametrize('replacement', ['modify', 'replace'])
def test_makemkv_rollback_preserves_foreign_replacement(tmp_path, monkeypatch, replacement):
    from dragontools.worker import iso_makemkv_service as module
    from dragontools.core.move_transaction import publish_staged_no_replace
    service, _, run = _makemkv_service(tmp_path, monkeypatch)
    def publish(stage, destination):
        if Path(destination).name == 'title02.mkv':
            first = tmp_path / 'title01.mkv'
            if replacement == 'replace':
                first.unlink()
            first.write_bytes(b'FOREIGN')
            raise FileExistsError('late collision')
        publish_staged_no_replace(stage, destination)
    monkeypatch.setattr(module, 'publish_staged_no_replace', publish)
    result = service.extract_titles('disc.iso', [1, 2], str(tmp_path), run_makemkv=run)
    assert not result.ok
    assert (tmp_path / 'title01.mkv').read_bytes() == b'FOREIGN'


def test_iso_failed_scan_cannot_discard_explicit_makemkv_selection():
    from dragontools.worker.iso_input_processor import ISOInputProcessor
    host = SimpleNamespace(ffmpeg_fallback=True, scan_only=False, selected_titles={'disc.iso': [4]},
        last_ffmpeg_fallback_error='', last_scan_error='failed scan', file_progress=_Signal(), file_result=_Signal(),
        log_message=lambda *a: None, scan_ffmpeg_fallback_titles=lambda _: [{'id': 0}],
        extract_with_ffmpeg_fallback=Mock(return_value=True))
    ISOInputProcessor(host)._handle_no_makemkv_titles('disc.iso', 'output')
    host.extract_with_ffmpeg_fallback.assert_not_called()
    assert host.file_result.calls[-1][1] is False


def test_audio_mux_source_replaced_during_tool_execution_is_preserved(tmp_path, monkeypatch):
    from dragontools.core.output_replace import commit_staged_output
    from dragontools.worker import audio_mux_job as module
    monkeypatch.setattr(module, 'commit_staged_output', partial(commit_staged_output, journal_root=tmp_path / 'journals'))
    source = tmp_path / 'audio source Ü.mkv'
    source.write_bytes(b'ORIGINAL')
    media = SimpleNamespace(video_streams=[object()], audio_streams=[object()],
                            subtitle_streams=[], analysis_source='test', duration_s=10)
    monkeypatch.setattr(module, 'analyze_media', lambda *a: media)
    worker = SimpleNamespace(progress_file=_Signal(), log_line=_Signal(), file_result=_Signal(),
        tools=SimpleNamespace(), overwrite_original=True, abort_requested=False, abort_type='sofort')
    planner = SimpleNamespace(build_audio_plan=lambda _: [], build_expected_contract=lambda *a: object(),
        build_output_path=lambda *a: (source, None), build_ffmpeg_cmd=lambda src, dst, plan: ['ffmpeg', dst])
    def run(cmd, *_):
        source.unlink()
        source.write_bytes(b'FOREIGN REPLACEMENT')
        Path(cmd[-1]).write_bytes(b'REMUX')
        return 0
    worker.run_ffmpeg_with_progress = run
    verifier = SimpleNamespace(verify=lambda **kw: SimpleNamespace(ok=True, messages=()))
    with pytest.raises(OSError, match='Originalquelle'):
        module.AudioMuxJobRunner(worker, planner=planner, verifier=verifier).run(str(source))
    assert source.read_bytes() == b'FOREIGN REPLACEMENT'
    assert not worker.file_result.calls


@pytest.mark.parametrize('mutation', ['source_before_journal', 'source_during_backup', 'stage_after_journal'])
def test_receipts_remain_authoritative_through_replace_commit(tmp_path, monkeypatch, mutation):
    from dragontools.core import output_replace as module
    from dragontools.core import move_transaction as transactions
    from dragontools.core.transaction_identity import path_receipt
    source, stage = tmp_path / 'source.mkv', tmp_path / 'verified.mkv'
    source.write_bytes(b'ORIGINAL')
    stage.write_bytes(b'VERIFIED OUTPUT')
    original_receipt, verified_receipt = path_receipt(source), path_receipt(stage)
    start = module.ReplaceJournal.start
    def create_journal(**kwargs):
        if mutation == 'source_before_journal':
            source.write_bytes(b'FOREIGN SOURCE')
        result = start(**kwargs)
        if mutation == 'stage_after_journal':
            stage.write_bytes(b'FOREIGN STAGE')
        return result
    monkeypatch.setattr(module.ReplaceJournal, 'start', create_journal)
    publish = transactions.publish_staged_no_replace
    def move_with_race(current, destination):
        if mutation == 'source_during_backup' and Path(current) == source:
            source.write_bytes(b'FOREIGN SOURCE')
        publish(current, destination)
    monkeypatch.setattr(transactions, 'publish_staged_no_replace', move_with_race)
    with pytest.raises(OSError):
        module.commit_staged_output(source=source, staging=stage, destination=source,
            log=lambda *a: None, journal_root=tmp_path / 'journals',
            expected_source_receipt=original_receipt, expected_staging_receipt=verified_receipt)
    assert source.read_bytes() == (b'ORIGINAL' if mutation == 'stage_after_journal' else b'FOREIGN SOURCE')
    assert stage.read_bytes() == (b'FOREIGN STAGE' if mutation == 'stage_after_journal' else b'VERIFIED OUTPUT')


def test_manual_fallback_selection_uses_a_distinct_title_namespace():
    from dragontools.worker.iso_input_processor import ISOInputProcessor
    from dragontools.worker.iso_models import FFMPEG_FALLBACK_TITLE_ID
    host = SimpleNamespace(ffmpeg_fallback=True, scan_only=False, auto_main_title=False,
        selected_titles={'disc.iso': [FFMPEG_FALLBACK_TITLE_ID]}, last_ffmpeg_fallback_error='',
        last_scan_error='', file_progress=_Signal(), file_result=_Signal(), log_message=lambda *a: None,
        scan_ffmpeg_fallback_titles=lambda _: [{'id': FFMPEG_FALLBACK_TITLE_ID}],
        extract_with_ffmpeg_fallback=Mock(return_value=True))
    assert FFMPEG_FALLBACK_TITLE_ID < 0
    ISOInputProcessor(host)._handle_no_makemkv_titles('disc.iso', 'output')
    host.extract_with_ffmpeg_fallback.assert_called_once_with('disc.iso', 'output')
    assert host.file_result.calls[-1][1] is True


def test_audio_mux_initial_analysis_uses_worker_owned_runner(tmp_path, monkeypatch):
    from dragontools.worker import audio_mux_job as module
    source = tmp_path / 'source.mkv'
    source.write_bytes(b'SOURCE')
    seen = []
    def analyze(path, tools, *, run_process=None):
        seen.append(run_process)
        return SimpleNamespace(video_streams=[], audio_streams=[])
    monkeypatch.setattr(module, 'analyze_media', analyze)
    worker = SimpleNamespace(tools=object(), abort_requested=False, abort_type='sofort',
        progress_file=_Signal(), file_result=_Signal(), log_line=_Signal())
    module.AudioMuxJobRunner(worker, planner=None, verifier=None).run(str(source))
    assert seen and callable(seen[0])


def test_mp4_verified_stage_is_retained_after_source_conflict(tmp_path):
    def run(cmd, *_):
        source.write_bytes(b'FOREIGN SOURCE')
        Path(cmd[-1]).write_bytes(b'VERIFIED REMUX')
        return 0
    service, source, stage, results, media = _mp4_job(tmp_path, run=run)
    assert not service.remux(str(source), str(source), media,
        current_index=1, total_files=1, user_abort_error=RuntimeError)
    assert stage.read_bytes() == b'VERIFIED REMUX'


def test_mp4_diagnostic_failure_cannot_change_a_committed_result(tmp_path):
    def run(cmd, *_):
        Path(cmd[-1]).write_bytes(b'VERIFIED REMUX')
        return 0
    service, source, stage, results, media = _mp4_job(tmp_path, run=run)
    service._logger = SimpleNamespace(file_start=lambda *a, **kw: None,
        file_done=Mock(side_effect=OSError('diagnostic unavailable')))
    assert service.remux(str(source), str(source), media,
        current_index=1, total_files=1, user_abort_error=RuntimeError)
    assert source.read_bytes() == b'VERIFIED REMUX'
    assert [entry[1] for entry in results] == [True]


def test_output_verification_rejects_a_file_changed_during_probe(tmp_path, monkeypatch):
    from dragontools.worker import output_verifier as module
    from dragontools.worker.output_probe import OutputProbeData
    path = tmp_path / 'output.mkv'
    path.write_bytes(b'ORIGINAL' * 512)
    def probe(*a, **kw):
        path.write_bytes(b'OTHER CONTENT' * 512)
        return OutputProbeData('matroska', 1.0, ({'codec_type': 'video', 'codec_name': 'h264'},))
    monkeypatch.setattr(module, 'probe_output', probe)
    result = module.OutputVerifier(ffprobe_path='ffprobe').verify(str(path), 'mkv')
    assert not result.ok
    assert path.read_bytes() == b'OTHER CONTENT' * 512


def test_owned_workspace_cleanup_does_not_delete_a_replaced_directory(tmp_path):
    from dragontools.worker.hdrplus_workspace import HDRPlusWorkspace
    workspace = HDRPlusWorkspace(tmp_path, 'owned_')
    original_root = workspace.root
    workspace.root.rename(tmp_path / 'retained_original')
    original_root.mkdir()
    foreign = original_root / 'foreign.txt'
    foreign.write_text('FOREIGN', encoding='utf-8')
    workspace.mark_persisted()
    workspace.finish()
    assert foreign.read_text(encoding='utf-8') == 'FOREIGN'


def test_makemkv_progress_error_cannot_reverse_a_verified_success(tmp_path, monkeypatch):
    service, worker, run = _makemkv_service(tmp_path, monkeypatch)
    def progress(path, percent, payload):
        if percent == 90:
            raise RuntimeError('GUI progress unavailable')
    service._progress = progress
    result = service.extract_titles('disc.iso', [1], str(tmp_path), run_makemkv=run)
    assert result.ok and (tmp_path / 'title01.mkv').is_file()
