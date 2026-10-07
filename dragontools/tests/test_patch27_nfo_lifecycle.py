"""Prepared NFO ownership survives refresh errors and fallible diagnostics."""
from concurrent.futures import Future
from types import SimpleNamespace as NS
import pytest
from dragontools.worker.postprocess_models import PreparedNfo
from dragontools.worker.postprocess_nfo_ownership import file_identity
from dragontools.worker.postprocess_runner import PostProcessService
from dragontools.worker.workflow_postprocess_commit import WorkflowPostprocessCommitService


@pytest.mark.parametrize('diagnostic_fails',[False,True])
def test_refresh_failure_retains_handle_until_owned_nfo_discard(tmp_path,diagnostic_fails):
    video=tmp_path/'Film.mkv'
    video.write_bytes(b'verified-video')
    target=tmp_path/'Film.nfo'
    target.write_text('<movie><title>User NFO</title></movie>',encoding='utf-8')
    staging=tmp_path/'.Film.__nfo_during__patch27.nfo'
    staging.write_text('<movie><title>Prepared NFO</title></movie>',encoding='utf-8')
    prepared=PreparedNfo(str(staging),str(target),'skip','movie',None,
        include_fileinfo=False,staging_identity=file_identity(staging))
    service=object.__new__(PostProcessService)
    def render(**kwargs): raise PermissionError('injected refresh write failure')
    service._render_prepared_nfo=render
    def warn(message):
        if diagnostic_fails: raise RuntimeError('injected closed diagnostic receiver')
    service._warn=warn
    future=Future(); future.set_result(prepared)
    ctx=NS(input_path=str(video),output_path=str(video),nfo_prepare_future=future,prepared_nfo=None,sidecar_paths=[])
    owner=WorkflowPostprocessCommitService(logger=NS(warn=lambda *a:None),result_service=None,
        sidecar_outputs={},postprocess_outputs={},service=service)
    if diagnostic_fails:
        with pytest.raises(RuntimeError,match='diagnostic'): owner.await_prepared_nfo(ctx)
        owner.discard_prepared_nfo(ctx)
    else:
        owner.await_prepared_nfo(ctx)
        assert ctx.prepared_nfo.status=='error'
        owner.commit_prepared_nfo(ctx,final_output=str(video))
        assert owner._postprocess_outputs[str(video)][0]['status']=='error'
    assert not staging.exists()
    assert target.read_text()=='<movie><title>User NFO</title></movie>'
    assert video.read_bytes()==b'verified-video'
