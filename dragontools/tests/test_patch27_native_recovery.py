"""Verified native media survives real workflow cleanup after post-step faults."""
import hashlib
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace as NS
import pytest
from dragontools.worker.workflow_engine import ConversionWorkflowRunner
from dragontools.worker.output_verifier import OutputVerifier
from dragontools.worker.cleanup_service import CleanupService


@pytest.mark.media_integration
@pytest.mark.parametrize('container',['mkv','mp4'])
@pytest.mark.parametrize('boundary',['nfo','trickplay','sidecar','install'])
def test_native_verified_candidate_survives_post_step_fault(tmp_path,container,boundary):
    ffmpeg,ffprobe=shutil.which('ffmpeg'),shutil.which('ffprobe')
    if not ffmpeg or not ffprobe: pytest.skip('FFmpeg/ffprobe unavailable')
    source=tmp_path/'Quelle ü.mkv'
    candidate=tmp_path/f'Kandidat ä.{container}'
    completed=subprocess.run([ffmpeg,'-v','error','-y','-f','lavfi','-i','color=s=64x64:r=25:d=0.4',
        '-c:v','libx264','-preset','ultrafast','-threads','1',str(source)],capture_output=True,timeout=30)
    assert completed.returncode==0,completed.stderr
    original=hashlib.sha256(source.read_bytes()).hexdigest()
    verification=OutputVerifier(ffprobe_path=ffprobe)
    def verified(): return verification.verify(str(candidate),container,expected_duration_ms=400)
    class Services:
        def analyze(self,ctx):
            ctx.output_path=str(candidate); ctx.base_dir=tmp_path
        def build_plan(self,ctx,override): pass
        def process(self,ctx,override):
            result=subprocess.run([ffmpeg,'-v','error','-y','-i',str(source),'-map','0:v:0','-c:v','copy',str(candidate)],
                capture_output=True,timeout=30)
            assert result.returncode==0,result.stderr
        def verify(self,ctx): assert verified().ok
        def replace(self,ctx): raise OSError(f'injected {boundary} failure before installation')
        def finalize(self,ctx): raise AssertionError('false success')
        def fail(self,ctx,reason,trace): assert not ctx.success
        def cleanup(self,ctx):
            CleanupService(overwrite_original=False,temp_overwrite_dir=lambda p:p/'tmp',log=lambda *a:None).cleanup_temp_artifacts(
                burn_sub_tmp=None,base_dir=tmp_path,output_path=ctx.output_path,keep_output=ctx.keep_failed_output)
    assert not ConversionWorkflowRunner(Services(),replace_original=True).run(str(source),{})
    assert hashlib.sha256(source.read_bytes()).hexdigest()==original
    assert candidate.exists() and verified().ok
