"""Workflow-stage faults exercise the real cleanup ownership boundary."""
from pathlib import Path
from types import SimpleNamespace as NS
import pytest

from dragontools.worker.workflow_engine import ConversionWorkflowRunner
from dragontools.worker.workflow_services import WorkflowServices
from dragontools.worker.cleanup_service import CleanupService


@pytest.mark.parametrize('stage',['analyze','plan','process','verify','nfo','source_trickplay','sidecars','replace','finalize'])
@pytest.mark.parametrize('fault',['error','timeout','cancel','shutdown'])
def test_stage_fault_never_reports_success_or_erases_verified_candidate(tmp_path,stage,fault):
    source=tmp_path/'Quelle Ü.mkv'
    candidate=tmp_path/'Kandidat ä.mkv'
    original=b'original-unchanged'
    source.write_bytes(original)
    calls=[]
    error=TimeoutError('injected timeout') if fault=='timeout' else RuntimeError(f'injected {fault}')
    def check(name):
        calls.append(name)
        if stage==name: raise error
    class Services:
        def analyze(self,ctx):
            ctx.base_dir=tmp_path
            ctx.output_path=str(candidate)
            check('analyze')
        def build_plan(self,ctx,override): check('plan')
        def process(self,ctx,override):
            candidate.write_bytes(b'completed-candidate')
            check('process')
        def verify(self,ctx): check('verify')
        def replace(self,ctx):
            for name in ['nfo','source_trickplay','sidecars','replace']: check(name)
            ctx.final_output_path=str(candidate)
        def finalize(self,ctx): check('finalize')
        def fail(self,ctx,reason,trace):
            calls.append('failed')
        def cleanup(self,ctx):
            calls.append('cleanup')
            CleanupService(overwrite_original=False,temp_overwrite_dir=lambda p:p/'tmp',log=lambda *a:None).cleanup_temp_artifacts(
                burn_sub_tmp=None,base_dir=tmp_path,output_path=ctx.output_path,
                keep_output=ctx.success or ctx.keep_failed_output)
    assert not ConversionWorkflowRunner(Services(),replace_original=True).run(str(source),{})
    assert calls.count('failed')==1 and calls.count('cleanup')==1
    assert source.read_bytes()==original
    if stage in {'nfo','source_trickplay','sidecars','replace','finalize'}:
        assert candidate.read_bytes()==b'completed-candidate'
    else:
        assert not candidate.exists()
