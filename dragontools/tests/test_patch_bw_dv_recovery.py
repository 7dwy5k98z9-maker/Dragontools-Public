from pathlib import Path
from types import SimpleNamespace

import pytest

from dragontools.worker.dv_pipeline_context import DVRunRequest, DVPipelineResult, DVPipelineState, DVWorkFiles
from dragontools.worker.dv_pipeline_runtime import DVPipelineRunExecutor
from dragontools.worker.dv_pipeline_stages import DVPipelineStages
from dragontools.worker.dv_runtime_models import DVTempState


def request(tmp_path):
    source = tmp_path / 'source.mkv'
    source.write_bytes(b'original')
    return DVRunRequest.create(input_path=str(source), output_path=str(tmp_path / 'work' / 'final.mkv'),
                               media_info=SimpleNamespace(subtitle_streams=[]), vf_args=[], audio_args=[],
                               audio_input_args=[], sn=[], crop=None, override={}, preserve_hdrplus=False,
                               container='mkv')


def test_subtitle_failure_stops_before_any_video_work(tmp_path):
    owner = object.__new__(DVPipelineStages)
    owner._temp_state = DVTempState()
    owner._initialize_run_state = lambda *_: None
    calls = []
    owner._prepare_subtitles = lambda *_: calls.append('subtitles') or False
    for method in ('_extract_source_hevc', '_convert_profile_to_81', '_extract_rpu',
                   '_reconcile_crop_from_rpu', '_encode_video', '_resolve_rpu_crop',
                   '_inject_dynamic_metadata', '_prepare_audio', '_mux_final_output'):
        setattr(owner, method, lambda *_: calls.append('video') or True)
    state = DVPipelineState(request(tmp_path), DVWorkFiles.create(tmp_path))
    result = owner.run(state, object())
    assert not result.success
    assert calls == ['subtitles']
    assert 'Untertitel' in result.failure_stage


@pytest.mark.parametrize('exception', [False, True])
def test_late_failure_archives_completed_encode_without_hdr10plus(tmp_path, exception):
    req = request(tmp_path)
    def run(state, _runner):
        state.files.enc_hevc.write_bytes(b'completed video')
        state.files.rpu_orig.write_bytes(b'rpu')
        (state.files.root / 'subtitle_0.sup').write_bytes(b'subtitle')
        state.video_encode_completed = True
        if exception:
            raise OSError('mux failure')
        return DVPipelineResult(False, failure_reason='mux failure', failure_stage='Final-Mux')
    executor = DVPipelineRunExecutor(temp_state=DVTempState(), worker=None, log=lambda *_: None,
                                    verbose_log=lambda *_: None, stages_factory=lambda: SimpleNamespace(run=run))
    result, state = executor.execute(req)
    archive = Path(result.failure_archive_path)
    assert not result.success
    assert result.preserve_failed_output
    assert (archive / 'encoded.hevc').read_bytes() == b'completed video'
    assert (archive / 'metadata.rpu').read_bytes() == b'rpu'
    assert (archive / 'subtitle_0.sup').exists()
    assert (archive / 'recovery.json').exists()
    assert not state.files.root.exists()
    assert all(Path(p).exists() for p in result.failure_artifact_paths)
    assert Path(req.input_path).read_bytes() == b'original'


@pytest.mark.parametrize('failure_point', ['rename', 'status'])
def test_failed_archive_never_deletes_completed_work(tmp_path, monkeypatch, failure_point):
    import dragontools.worker.dv_failure_recovery as module
    req = request(tmp_path)
    def fail(*_args, **_kwargs):
        raise OSError('disk unavailable')
    if failure_point == 'rename':
        monkeypatch.setattr(module.os, 'rename', fail)
    else:
        monkeypatch.setattr(Path, 'write_text', fail)
    def run(state, _runner):
        state.files.enc_hevc.write_bytes(b'complete')
        state.video_encode_completed = True
        return DVPipelineResult(False, failure_reason='audio error')
    executor = DVPipelineRunExecutor(temp_state=DVTempState(), worker=None, log=lambda *_: None,
                                    verbose_log=lambda *_: None, stages_factory=lambda: SimpleNamespace(run=run))
    result, state = executor.execute(req)
    assert not result.failure_archive_path
    assert result.preserve_failed_output
    assert state.files.enc_hevc.read_bytes() == b'complete'
    assert str(state.files.root) in result.failure_artifact_paths


@pytest.mark.parametrize('success', [False, True])
def test_success_or_incomplete_encode_cleans_temporary_files(tmp_path, success):
    req = request(tmp_path)
    def run(state, _runner):
        state.files.enc_hevc.write_bytes(b'video data')
        state.video_encode_completed = success
        return DVPipelineResult(success)
    executor = DVPipelineRunExecutor(temp_state=DVTempState(), worker=None, log=lambda *_: None,
                                    verbose_log=lambda *_: None, stages_factory=lambda: SimpleNamespace(run=run))
    result, state = executor.execute(req)
    assert result.success == success
    assert not result.preserve_failed_output
    assert not state.files.root.exists()
    assert not (tmp_path / 'Archiv').exists()


def test_successful_subtitle_preparation_is_run_once_before_encoder(tmp_path):
    owner = object.__new__(DVPipelineStages)
    owner._temp_state = DVTempState()
    owner._initialize_run_state = lambda *_: None
    owner._subtitle_rules = {}
    owner._log = lambda *_: None
    calls = []
    for name in ('_prepare_subtitles', '_extract_source_hevc', '_convert_profile_to_81', '_extract_rpu',
                 '_reconcile_crop_from_rpu', '_encode_video', '_resolve_rpu_crop',
                 '_inject_dynamic_metadata', '_prepare_audio', '_mux_final_output'):
        setattr(owner, name, lambda *_args, name=name: calls.append(name) or True)
    req = request(tmp_path)
    Path(req.output_path).parent.mkdir()
    Path(req.output_path).write_bytes(b'final')
    state = DVPipelineState(req, DVWorkFiles.create(tmp_path))
    assert owner.run(state, object()).success
    assert calls[0] == '_prepare_subtitles'
    assert calls.count('_prepare_subtitles') == 1
    assert calls.index('_prepare_subtitles') < calls.index('_encode_video')
