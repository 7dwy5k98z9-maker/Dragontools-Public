"""Final cross-boundary stress: scheduling ownership and native concurrent moves."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import random
from types import SimpleNamespace as NS

import pytest

from dragontools.tests.test_parallel_converter_thread import (
    FakeWorker, _install_parallel_fakes, _thread, _complete,
)


@pytest.mark.parametrize('seed', [28, 281, 282])
def test_reorder_pause_and_stale_callbacks_never_duplicate_48_jobs(monkeypatch, seed):
    module, _ = _install_parallel_fakes(monkeypatch)
    monkeypatch.setattr(module.ParallelConverterThread, '_initialize_gpu_log_context',
        lambda self: (setattr(self, '_log_gpu_list', []), setattr(self, '_log_enc_name', 'cpu')))
    files = [f'C:/Media Ü/Job {n:02}.mkv' for n in range(48)]
    parent = _thread(module, files, jobs=4)
    events = []
    parent.file_result.connect(lambda *args: events.append(args))
    parent.start()
    rng = random.Random(seed)
    completed = []
    while parent.isRunning():
        order = list(files)
        rng.shuffle(order)
        parent.reorder_waiting_files(order)
        active = [child for child in FakeWorker.instances if child.isRunning()]
        assert 1 <= len(active) <= 4
        child = active[0]
        path = child.files[0]
        assert parent.set_file_paused(path, True)
        assert child._paused and all(not other._paused for other in active[1:])
        assert parent.encode_active_count() == len(active)
        assert parent.set_file_paused(path, False)
        _complete(parent, child)
        completed.append(path)
        count = len(events)
        # Duplicate terminal notifications must not advance or finalize a new owner.
        parent._on_child_file_result(child, path, path+'.out', '✅')
        parent._on_child_finished(child)
        assert len(events) == count
        assert len(FakeWorker.instances) <= len(files)
    assert set(completed) == set(files) and len(completed) == 48
    assert len(events) == 48
    assert len({child.files[0] for child in FakeWorker.instances}) == 48
    assert parent.aggregate_progress_percent() == 100


@pytest.mark.media_integration
def test_six_native_jobs_share_target_without_cross_job_artifacts(tmp_path):
    from dragontools.tests.test_patch26_native_chain import CASES, test_native_contract_chain
    from dragontools.core.move_file_service import MoveFileService
    from dragontools.core.move_journal import MoveJournal
    from dragontools.core.move_journal_recovery import recover_interrupted_backups
    target = tmp_path/'Gemeinsames Ziel Ü'; target.mkdir()
    def job(item):
        n, case = item
        root = tmp_path/f'Worker {n}'; root.mkdir()
        test_native_contract_chain(*case, root)
        source = root/f'Quelle Ü.{case[0]}'
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        candidate = root/f'Ausgabe ä.{case[1]}'
        unique = root/f'Job {n:02}.{case[1]}'
        candidate.rename(unique)
        expected = hashlib.sha256(unique.read_bytes()).hexdigest()
        journal = MoveJournal.start(files=[str(unique)], root=root)
        journal.start_file(str(unique), target_dir=str(target), dest_path=str(target/unique.name))
        service = MoveFileService(conflict_mode='skip', log=lambda *a:None, wait=lambda:None,
            abort_immediately=lambda:False, journal=journal)
        ok, result = service.move(str(unique), str(target))
        assert ok and result['ok'] and not result.get('cleanup_pending')
        final = target/unique.name
        assert not unique.exists() and final.is_file()
        assert hashlib.sha256(final.read_bytes()).hexdigest() == expected
        assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
        recovered = recover_interrupted_backups(journal.data)
        assert recovered['ambiguous'] == recovered['failed'] == recovered['cleaned'] == 0
        repeated = recover_interrupted_backups(journal.data)
        assert repeated['completed'] == repeated['cleaned'] == 0
        return final.name, expected
    with ThreadPoolExecutor(max_workers=3) as pool:
        outputs = list(pool.map(job, enumerate(CASES)))
    assert len(outputs) == len(list(target.iterdir())) == 6
    assert len({name for name, _ in outputs}) == 6
    assert not list(tmp_path.rglob('*.__dragontools_partial__*'))


@pytest.mark.parametrize('container', ['mkv', 'mp4'])
@pytest.mark.parametrize('hdr', ['dv', 'hdr10plus'])
@pytest.mark.parametrize('mode', ['encode', 'strip'])
def test_av1_beta_policy_is_explicit_in_final_matrix(container, hdr, mode):
    from dragontools.core.models import MediaInfo, VideoStream
    from dragontools.core.rules_preview import build_rules_preview
    from dragontools.worker.pipeline_decision_service import PipelineDecisionService
    from dragontools.tests.test_patch26_contract_matrix import _Log
    from dragontools.core.settings_conversion import SET_KEY_OUTPUT_CONTAINER_STANDARD, SET_KEY_OUTPUT_CONTAINER_DV
    video = VideoStream(0, 'av1', 1920, 1080, bit_depth=10,
        has_dolby_vision=hdr=='dv', has_hdr10plus=hdr=='hdr10plus',
        hdr_format='dolby_vision' if hdr=='dv' else 'hdr10plus')
    media = MediaInfo('AV1 Ü.mkv', [], [], [video], is_hdr=True,
        dolby_vision=hdr=='dv', dv_profile_major=10 if hdr=='dv' else None,
        has_hdr10plus=hdr=='hdr10plus')
    options = {'preserve_dv':True, 'preserve_hdrplus':True}
    override = {'processing_mode':'strip_only'} if mode=='strip' else {}
    preview = build_rules_preview(media.path, codec='av1', media_info=media,
        file_override=override, default_encoder_options=options,
        standard_container=container, dv_container=container)
    settings = NS(value=lambda key, default=None, **kw:
        container if key in {SET_KEY_OUTPUT_CONTAINER_STANDARD, SET_KEY_OUTPUT_CONTAINER_DV} else default)
    runtime = PipelineDecisionService(codec='av1', encoder_options=options,
        file_overrides={}, settings=settings, logger=_Log())
    pipeline, actual_container = runtime.select_pipeline_context(media.path, media, override,
        effective_codec='av1', effective_encoder_options=options)
    assert pipeline == preview['pipeline'] == ('av1_dv' if hdr=='dv' else 'av1_hdrplus')
    assert actual_container == preview['target_container'] == container
