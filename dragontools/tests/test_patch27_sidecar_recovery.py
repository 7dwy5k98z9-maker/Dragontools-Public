"""Real-filesystem rollback retry and orchestrator cleanup fault injection."""
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from dragontools.core.sidecar_transaction import SidecarCommitTransaction, SidecarCommitError
from dragontools.worker.dv_remux_job import DVRemuxJobRunner
from dragontools.worker.workflow_sidecar_commit import WorkflowSidecarCommitService
from dragontools.worker.cleanup_service import CleanupService


class Log:
    def __getattr__(self,name): return lambda *a,**k: None


def transaction(tmp_path, count=2):
    sources=[]
    for language in ['de','en'][:count]:
        source=tmp_path/f'Film.__tmp__.{language}.srt'
        source.write_text(f'new-{language}',encoding='utf-8')
        (tmp_path/f'Film.{language}.srt').write_text(f'old-{language}',encoding='utf-8')
        sources.append(str(source))
    return SidecarCommitTransaction(sources,source_base=tmp_path/'Film.__tmp__',destination_base=tmp_path/'Film'),sources


def lock_backup(monkeypatch, language='en'):
    import dragontools.core.sidecar_transaction as module
    publish=module.publish_staged_no_replace
    locked={'value':True}
    def guarded(source,destination):
        if locked['value'] and str(source).endswith(f'{language}.srt.dragontools_backup'):
            raise PermissionError('injected locked old sidecar backup')
        return publish(source,destination)
    monkeypatch.setattr(module,'publish_staged_no_replace',guarded)
    return locked


def test_successful_rollback_is_idempotent_with_old_sidecars(tmp_path):
    tx,sources=transaction(tmp_path)
    tx.commit()
    tx.rollback()
    before={p.name:p.read_bytes() for p in tmp_path.iterdir()}
    tx.rollback()
    assert {p.name:p.read_bytes() for p in tmp_path.iterdir()}==before
    assert tx.final_paths==[]
    assert all(Path(p).exists() for p in sources)


def test_partial_rollback_retries_only_pending_records(tmp_path,monkeypatch):
    tx,sources=transaction(tmp_path)
    tx.commit()
    locked=lock_backup(monkeypatch)
    with pytest.raises(SidecarCommitError): tx.rollback()
    with pytest.raises(SidecarCommitError, match='Rollback'):
        tx.commit()
    assert (tmp_path/'Film.de.srt').read_text()=='old-de'
    assert (tmp_path/'Film.en.srt.dragontools_backup').read_text()=='old-en'
    locked['value']=False
    tx.rollback()
    tx.rollback()
    assert all(Path(p).exists() for p in sources)
    assert (tmp_path/'Film.en.srt').read_text()=='old-en'
    assert not list(tmp_path.glob('*.dragontools_backup'))


def test_dv_failed_sidecar_commit_retains_recovery_until_restart(tmp_path,monkeypatch):
    import dragontools.worker.dv_remux_job as module
    from dragontools.core.sidecar_journal import SidecarJournal,recover_active_sidecar_journals
    from dragontools.tests.test_review_patch_v12_dv_transaction_safety import _worker,_runner
    source=tmp_path/'Film.mkv'
    source.write_bytes(b'original')
    staging=tmp_path/'Film.__tmp__.mp4'
    transaction_model,sources=transaction(tmp_path)
    original_start=SidecarJournal.start
    monkeypatch.setattr(module.SidecarJournal,'start',lambda **kw:original_start(**kw,root=tmp_path))
    original_commit=SidecarCommitTransaction.commit
    def committed_then_failed(self):
        original_commit(self)
        raise SidecarCommitError('injected failure after all sidecars committed')
    monkeypatch.setattr(SidecarCommitTransaction,'commit',committed_then_failed)
    locked=lock_backup(monkeypatch)
    class Manager:
        def build_output_path(self,path): return str(staging)
        def verify_output(self,**kw): return True
        def replace_output_if_needed(self,*a): raise AssertionError('must not install failed sidecars')
        def cleanup_incomplete(self,*a): staging.unlink(missing_ok=True)
    worker=_worker()
    runner=_runner(worker,source,staging,Manager())
    monkeypatch.setattr(runner,'_export_sidecars_if_needed',lambda **kw:sources)
    assert not runner.run(str(source))
    assert source.read_bytes()==b'original'
    assert staging.exists() and all(Path(p).exists() for p in sources)
    assert len(list((tmp_path/'SidecarJournal').glob('*.json')))==1
    assert not any(call[-1]=='✅' for call in worker.file_result.calls)
    locked['value']=False
    recovery=recover_active_sidecar_journals(tmp_path)
    assert recovery=={'rolled_back':1,'completed':0,'pending':0,'failed':0}
    assert recover_active_sidecar_journals(tmp_path)==dict.fromkeys(recovery,0)
    assert source.read_bytes()==b'original' and staging.exists()
    assert (tmp_path/'Film.de.srt').read_text()=='old-de'
    assert (tmp_path/'Film.en.srt').read_text()=='old-en'


def test_dv_rollback_keeps_every_staging_sidecar_if_recovery_incomplete(tmp_path,monkeypatch):
    tx,sources=transaction(tmp_path)
    tx.commit()
    lock_backup(monkeypatch)
    runner=object.__new__(DVRemuxJobRunner)
    runner.worker=NS(log=lambda *a: None)
    runner._rollback_sidecars(tx,sources)
    assert all(Path(p).exists() for p in sources), 'rolled-back new tracks remain recovery artifacts'
    assert (tmp_path/'Film.en.srt.dragontools_backup').read_text()=='old-en'


@pytest.mark.parametrize('boundary',['commit','replace'])
def test_workflow_rollback_error_vetoes_later_cleanup(tmp_path,monkeypatch,boundary):
    from dragontools.core.sidecar_journal import SidecarJournal
    import dragontools.worker.workflow_sidecar_commit as module
    tx,sources=transaction(tmp_path)
    candidate=tmp_path/'Film.__tmp__.mkv'
    candidate.write_bytes(b'completed-video-candidate')
    ctx=NS(input_path=str(tmp_path/'original.mkv'),output_path=str(candidate),
        sidecar_paths=sources,keep_failed_output=False)
    service=WorkflowSidecarCommitService(logger=Log(),sidecar_outputs={})
    original_start=SidecarJournal.start
    monkeypatch.setattr(module.SidecarJournal,'start',lambda **kw:original_start(**kw,root=tmp_path))
    lock_backup(monkeypatch)
    if boundary=='commit':
        original_commit=SidecarCommitTransaction.commit
        def commit_then_fail(self):
            original_commit(self)
            raise SidecarCommitError('injected late commit failure')
        monkeypatch.setattr(SidecarCommitTransaction,'commit',commit_then_fail)
        with pytest.raises(RuntimeError):
            service.commit(ctx,final_output=str(tmp_path/'Film.mkv'),store_result=False)
    else:
        tx.commit()
        with pytest.raises(RuntimeError): service.rollback(tx,ctx,sources)
    assert ctx.keep_failed_output
    CleanupService(overwrite_original=False,temp_overwrite_dir=lambda p:p/'tmp',log=lambda *a:None).cleanup_temp_artifacts(
        burn_sub_tmp=None,base_dir=tmp_path,output_path=str(candidate),sidecar_paths=sources,
        keep_output=ctx.keep_failed_output)
    assert candidate.read_bytes()==b'completed-video-candidate'
    assert all(Path(p).exists() for p in sources)
    assert (tmp_path/'Film.en.srt.dragontools_backup').read_text()=='old-en'
