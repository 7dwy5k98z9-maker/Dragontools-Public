from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from dragontools.worker.dv_failure_recovery import DVFailureRecovery
from dragontools.worker.dv_pipeline_context import DVPipelineState, DVRunRequest, DVWorkFiles
from dragontools.worker.dv_runtime_models import DVTempState
from dragontools.worker.dv_workflow_pipeline_adapter import DVPipelineExecutorAdapter
from dragontools.worker.workflow_models import PipelineExecutionRequest


def _state(tmp_path: Path, *, with_output: bool = True) -> DVPipelineState:
    source = tmp_path / "Film.source.mkv"
    source.write_bytes(b"original-source")
    output = tmp_path / "Film.mkv"
    if with_output:
        output.write_bytes(b"final-candidate")

    work = tmp_path / "temp"
    work.mkdir()
    files = DVWorkFiles.create(work)
    files.enc_hevc.write_bytes(b"encoded")
    files.hdr10plus_hevc.write_bytes(b"hdr10plus-stream")
    files.injected.write_bytes(b"dv-hdr10plus-stream")
    files.hdr10plus_json.write_text('{"SceneInfo": []}', encoding="utf-8")
    files.hdr10plus_verify_json.write_text('{"verify": false}', encoding="utf-8")
    files.rpu_orig.write_bytes(b"rpu-original")
    files.rpu_final.write_bytes(b"rpu-used")
    files.rpu_verify.write_bytes(b"rpu-verify")

    request = DVRunRequest.create(
        input_path=str(source),
        output_path=str(output),
        media_info=SimpleNamespace(),
        vf_args=[],
        audio_args=[],
        audio_input_args=[],
        sn=["-sn"],
        crop=None,
        override={},
        preserve_hdrplus=False,
        generate_hdr10plus=True,
        container="mkv",
    )
    state = DVPipelineState(request=request, files=files)
    state.rpu_to_use = files.rpu_final
    return state


def test_failed_hdr10plus_proof_archives_video_json_and_rpu(tmp_path):
    logs = []
    state = _state(tmp_path)
    recovery = DVFailureRecovery(log=lambda message, level="info": logs.append((level, message)))

    bundle, artifacts = recovery.preserve_dynamic_metadata_failure(
        state=state,
        reason="HDR10+ im finalen MKV nicht nachweisbar",
        stage="STEP 7/7 Final-Mux/Metadatenprüfung",
    )

    assert bundle is not None
    assert bundle.parent == tmp_path / "Archiv"
    assert not Path(state.request.output_path).exists()
    assert (bundle / "Film.mkv").read_bytes() == b"final-candidate"
    assert (bundle / "Film.hdr10plus.json").exists()
    assert (bundle / "Film.hdr10plus.verify.json").exists()
    assert (bundle / "Film.rpu").read_bytes() == b"rpu-used"
    assert (bundle / "Film.rpu_original.bin").read_bytes() == b"rpu-original"
    assert (bundle / "Film.rpu_verify.bin").read_bytes() == b"rpu-verify"
    assert (bundle / "status.txt").exists()
    assert Path(state.request.input_path).read_bytes() == b"original-source"
    assert str(bundle / "Film.mkv") in artifacts


def test_failed_hdr10plus_proof_keeps_best_hevc_when_final_mux_missing(tmp_path):
    state = _state(tmp_path, with_output=False)
    recovery = DVFailureRecovery(log=lambda *_args, **_kwargs: None)

    bundle, _ = recovery.preserve_dynamic_metadata_failure(
        state=state,
        reason="HDR10+ nach DV-Injection nicht nachweisbar",
        stage="STEP 6/7 Dynamische Metadaten",
    )

    assert bundle is not None
    assert (bundle / "Film.injected.hevc").read_bytes() == b"dv-hdr10plus-stream"
    assert (bundle / "Film.hdr10plus.json").exists()
    assert (bundle / "Film.rpu").exists()


def test_pipeline_adapter_propagates_failure_archive_contract(tmp_path):
    class Pipeline:
        last_sidecar_paths = []
        last_hdr10plus_verified = False
        last_dolby_vision_verified = False
        last_dv_crop_alignment_verified = False
        last_final_rpu_checked = False
        last_final_rpu_present = False
        last_final_rpu_matches_injected = None
        last_final_rpu_expected_sha256 = ""
        last_final_rpu_actual_sha256 = ""
        last_final_rpu_level5_offsets = ()
        last_final_rpu_level5_dynamic = False
        last_final_rpu_message = ""
        last_failure_reason = "HDR10+ nicht nachweisbar"
        last_failure_stage = "STEP 7/7 Final-Mux/Metadatenprüfung"
        last_tool_output = ""
        last_effective_crop = None
        last_failure_archive_path = str(tmp_path / "Archiv" / "bundle")
        last_failure_artifact_paths = (str(tmp_path / "Archiv" / "bundle" / "Film.mkv"),)
        last_preserve_failed_output = False

        def configure_encoder(self, _config):
            return None

        def run(self, **_kwargs):
            return False

    adapter = DVPipelineExecutorAdapter(Pipeline(), DVTempState())
    request = PipelineExecutionRequest(
        pipeline="dv",
        input_path="in.mkv",
        output_path="out.mkv",
        container="mkv",
        media_info=SimpleNamespace(),
        plan=SimpleNamespace(vf_args=[], audio_args=[], audio_input_args=[], sn=["-sn"], crop=None, burn_sub_or_vf=False),
        override={},
        strip_only=False,
        duration_ms=None,
        codec="h265",
        crf=22,
        preset="medium",
        encoder_options={},
        generate_hdr10plus=True,
    )
    result = adapter.execute(request)
    assert result.success is False
    assert result.failure_archive_path.endswith("bundle")
    assert result.failure_artifact_paths
    assert result.preserve_failed_output is False


def test_final_mux_metadata_failure_archives_before_temp_cleanup(tmp_path, monkeypatch):
    import dragontools.worker.dv_pipeline_stages as stages_module
    from dragontools.worker.dv_pipeline_stages import DVPipelineStages

    state = _state(tmp_path)
    temp_state = DVTempState()
    temp_state.record_failure(
        reason="HDR10+-Metadaten sind nach dem MKV-Mux nicht identisch nachweisbar.",
        stage="STEP 7/7 Post-Mux Metadaten-Fallbackprüfung",
    )
    recovery = DVFailureRecovery(log=lambda *_args, **_kwargs: None)
    stages = DVPipelineStages(
        tools=SimpleNamespace(),
        encoder_config=SimpleNamespace(),
        progress_runner=None,
        temp_state=temp_state,
        audio_mux_service=None,
        mp4box_muxer=None,
        mkv_muxer=None,
        rpu_service=None,
        hdr10plus_service=None,
        generator_client=None,
        level5_editor=None,
        subtitle_service=None,
        subtitle_mux_service=None,
        subtitle_rules={},
        failure_recovery=recovery,
        log=lambda *_args, **_kwargs: None,
        verbose_log=lambda *_args, **_kwargs: None,
        assert_nonempty_file=lambda *_args, **_kwargs: True,
        clear_burn_sub_tmp=lambda: None,
    )
    monkeypatch.setattr(
        stages_module,
        "_mux_service",
        lambda _owner: SimpleNamespace(mux_final_output=lambda *_args, **_kwargs: False),
    )

    assert stages._mux_final_output(state, SimpleNamespace()) is False
    bundle = Path(state.failure_archive_path)
    assert bundle.exists()
    assert (bundle / "Film.mkv").exists()
    assert (bundle / "Film.hdr10plus.json").exists()
    assert (bundle / "Film.rpu").exists()
    assert not Path(state.request.output_path).exists()


def test_partial_diagnostic_archive_keeps_temp_json_and_rpu_after_pipeline_exit(tmp_path, monkeypatch):
    import dragontools.worker.dv_failure_recovery as recovery_module
    from dragontools.worker.dv_pipeline_context import DVPipelineResult
    from dragontools.worker.dv_pipeline_runtime import DVPipelineRunExecutor

    source = tmp_path / "Film.source.mkv"
    source.write_bytes(b"source")
    output = tmp_path / "Film.mkv"
    request = DVRunRequest.create(
        input_path=str(source),
        output_path=str(output),
        media_info=SimpleNamespace(),
        vf_args=[],
        audio_args=[],
        audio_input_args=[],
        sn=["-sn"],
        crop=None,
        override={},
        preserve_hdrplus=False,
        generate_hdr10plus=True,
        container="mkv",
    )

    real_copy2 = recovery_module.shutil.copy2

    def fail_json_copy(src, dst, *args, **kwargs):
        if Path(src).name == "metadata_hdr10plus.json":
            raise PermissionError("simulated JSON lock")
        return real_copy2(src, dst, *args, **kwargs)

    monkeypatch.setattr(recovery_module.shutil, "copy2", fail_json_copy)
    logs = []
    recovery = DVFailureRecovery(log=lambda message, level="info": logs.append((level, message)))

    class Stages:
        def run(self, state, _runner):
            output.write_bytes(b"final-candidate")
            state.files.enc_hevc.write_bytes(b"encoded")
            state.files.hdr10plus_json.write_text('{"SceneInfo": []}', encoding="utf-8")
            state.files.rpu_final.write_bytes(b"rpu")
            state.rpu_to_use = state.files.rpu_final
            bundle, artifacts = recovery.preserve_dynamic_metadata_failure(
                state=state,
                reason="simulated verify failure",
                stage="STEP 7/7",
            )
            assert bundle is None
            state.failure_artifact_paths = list(artifacts)
            state.preserve_failed_output = True
            return DVPipelineResult(
                False,
                failure_reason="simulated verify failure",
                failure_stage="STEP 7/7",
                failure_artifact_paths=tuple(artifacts),
                preserve_failed_output=True,
            )

    executor = DVPipelineRunExecutor(
        temp_state=DVTempState(),
        worker=SimpleNamespace(),
        log=lambda message, level="info": logs.append((level, message)),
        verbose_log=lambda *_args: None,
        stages_factory=lambda: Stages(),
    )
    result, state = executor.execute(request)

    assert result.success is False
    assert result.preserve_failed_output is True
    assert state.files.root.exists(), "DV temp tree must survive incomplete archive persistence"
    assert state.files.hdr10plus_json.read_text(encoding="utf-8") == '{"SceneInfo": []}'
    assert state.files.rpu_final.read_bytes() == b"rpu"
    partial_dirs = list((tmp_path / "Archiv").glob(".*.partial"))
    assert partial_dirs, "successful staged artifacts should remain available for diagnosis"
