from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from dragontools.core.encoder_profile_override import effective_encoder_settings
from dragontools.core.models import MediaInfo, VideoStream
from dragontools.core.rules_preview import build_rules_preview
from dragontools.worker.av1_metadata_pipeline import _AV1MetadataPipelineBase
from dragontools.worker.pipeline_decision_service import PipelineDecisionService
from dragontools.worker.standard_pipeline_runner import StandardPipelineRunner
from dragontools.worker.subtitle_sidecar_service import SubtitleExportFailure, SubtitleExportResult
from dragontools.worker.workflow_models import PipelineExecutionRequest, PipelineExecutionResult
from dragontools.worker.workflow_services import WorkflowServices


class _Settings:
    def value(self, _key, default=None, type=None):
        return default


class _Logger:
    def info(self, _message):
        pass

    def info_short(self, _message):
        pass


class _Archive:
    def __init__(self):
        self.calls = []

    def archive_original(self, path, reason):
        self.calls.append((path, reason))


def _dv_media() -> MediaInfo:
    video = VideoStream(
        index=0,
        codec="hevc",
        width=3840,
        height=2160,
        hdr_format="dolby_vision",
        has_dolby_vision=True,
    )
    return MediaInfo(
        path="film.mkv",
        audio_streams=[],
        subtitle_streams=[],
        video_streams=[video],
        dolby_vision=True,
        dv_profile="8",
        dv_profile_major=8,
    )


def _profile(*, preserve_dv: bool) -> dict:
    return {
        "key": "review24",
        "label": "Review24",
        "codec": "h265",
        "crf": 22,
        "preset": "medium",
        "scale": "original",
        "encoder_options": {"encoder": "cpu", "preserve_dv": preserve_dv},
    }


def _request(tmp_path: Path) -> PipelineExecutionRequest:
    return PipelineExecutionRequest(
        pipeline="standard",
        input_path=str(tmp_path / "source.mkv"),
        output_path=str(tmp_path / "encoded.mp4"),
        container="mp4",
        media_info=SimpleNamespace(),
        plan=None,
        override={},
        strip_only=False,
        duration_ms=1000,
        codec="h265",
        crf=22,
        preset="medium",
    )


def _failed_export() -> SubtitleExportResult:
    return SubtitleExportResult(
        planned_stream_indices=(3,),
        exported_paths=(),
        failures=(SubtitleExportFailure(3, "de", "hdmv_pgs_subtitle", "ffmpeg rc=1"),),
    )


def test_encoder_profile_hdr_policy_is_identical_in_preflight_and_runtime():
    media = _dv_media()
    override = {"encoder_profile": _profile(preserve_dv=False)}
    global_options = {"encoder": "cpu", "preserve_dv": True, "preserve_hdrplus": True}

    preview = build_rules_preview(
        "film.mkv",
        codec="h265",
        file_override=override,
        media_info=media,
        default_encoder_options=global_options,
        standard_container="mkv",
        dv_container="mp4",
    )
    assert preview["pipeline"] == "standard"
    assert preview["target_container"] == "mkv"
    assert preview["effective_preserve_dv"] is False

    effective = effective_encoder_settings(
        default_codec="h265",
        default_crf=23,
        default_preset="medium",
        default_scale_mode="original",
        default_encoder_options=global_options,
        file_override=override,
    )
    service = PipelineDecisionService(
        codec="h265",
        encoder_options=global_options,
        file_overrides={},
        settings=_Settings(),
        logger=_Logger(),
        archive_service=_Archive(),
    )
    pipeline, container = service.select_pipeline_context(
        "film.mkv",
        media,
        override,
        effective_encoder_options=effective["encoder_options"],
        effective_codec=effective["codec"],
    )
    assert (pipeline, container) == ("standard", "mkv")
    assert service.last_selection["effective_preserve_dv"] is False


def test_explicit_per_file_hdr_override_still_wins_over_assigned_profile():
    media = _dv_media()
    override = {
        "encoder_profile": _profile(preserve_dv=False),
        "preserve_dv": True,
    }
    effective = effective_encoder_settings(
        default_codec="h265",
        default_crf=23,
        default_preset="medium",
        default_scale_mode="original",
        default_encoder_options={"preserve_dv": True},
        file_override=override,
    )
    service = PipelineDecisionService(
        codec="h265",
        encoder_options={"preserve_dv": True},
        file_overrides={},
        settings=_Settings(),
        logger=_Logger(),
        archive_service=_Archive(),
    )
    assert service.select_pipeline_context(
        "film.mkv",
        media,
        override,
        effective_encoder_options=effective["encoder_options"],
        effective_codec=effective["codec"],
    ) == ("dv", "mp4")


def test_standard_sidecar_failure_preserves_completed_video_candidate(tmp_path):
    runner = StandardPipelineRunner.__new__(StandardPipelineRunner)
    runner._subtitle_rules = {}
    runner._subtitle_service = SimpleNamespace(export_sidecars_result=lambda **_kw: _failed_export())

    result = runner._finish_sidecars(_request(tmp_path))

    assert result.success is False
    assert result.failure_stage == "Untertitel-Export"
    assert result.preserve_failed_output is True


def test_av1_sidecar_failure_preserves_completed_video_candidate(tmp_path):
    pipeline = _AV1MetadataPipelineBase.__new__(_AV1MetadataPipelineBase)
    pipeline._subtitle_rules = {}
    pipeline._subtitle_service = SimpleNamespace(export_sidecars_result=lambda **_kw: _failed_export())
    pipeline._tools = SimpleNamespace(ffmpeg="ffmpeg.exe")
    pipeline._temp_state = SimpleNamespace(record_failure=lambda **_kw: None)
    pipeline._log_fn = lambda *_args, **_kwargs: None

    _sidecars, result = pipeline._export_mp4_sidecars(_request(tmp_path))

    assert result is not None
    assert result.success is False
    assert result.preserve_failed_output is True


def test_preserve_failed_output_contract_reaches_generic_cleanup():
    cleanup_calls = []
    services = WorkflowServices.__new__(WorkflowServices)
    services._logger = SimpleNamespace(warn=lambda *_args: None)
    services._temp_state = SimpleNamespace(burn_sub_tmp=None)
    services._output_commit = SimpleNamespace(discard_prepared_nfo=lambda _ctx: None)
    services._cleanup_service = SimpleNamespace(
        cleanup_temp_artifacts=lambda **kwargs: cleanup_calls.append(kwargs)
    )
    ctx = SimpleNamespace(
        sidecar_paths=[],
        pipeline_verified_hdr10plus=False,
        pipeline_verified_dolby_vision=False,
        pipeline_verified_dv_crop_alignment=False,
        pipeline_final_rpu_checked=False,
        pipeline_final_rpu_present=False,
        pipeline_final_rpu_matches_injected=None,
        pipeline_final_rpu_expected_sha256="",
        pipeline_final_rpu_actual_sha256="",
        pipeline_final_rpu_level5_offsets=(),
        pipeline_final_rpu_level5_dynamic=False,
        pipeline_final_rpu_message="",
        replacement_archived_path="",
        keep_failed_output=False,
        success=False,
        base_dir=Path("."),
        output_path="finished_candidate.mkv",
    )

    services._apply_pipeline_result_state(
        ctx,
        PipelineExecutionResult(False, preserve_failed_output=True),
    )
    services.cleanup(ctx)

    assert ctx.keep_failed_output is True
    assert cleanup_calls[-1]["keep_output"] is True


def test_strip_only_uses_source_codec_for_dynamic_hdr_policy_and_preflight():
    media = _dv_media()
    override = {"processing_mode": "strip_only"}
    preview = build_rules_preview(
        "film.mkv",
        codec="h264",
        file_override=override,
        media_info=media,
        default_encoder_options={"preserve_dv": True},
        standard_container="mkv",
        dv_container="mp4",
    )
    assert preview["pipeline"] == "dv"
    assert preview["target_container"] == "mp4"
    assert preview["should_archive"] is False


def test_strip_only_planning_does_not_treat_configured_h264_as_actual_video_codec():
    from dragontools.worker.workflow_models import WorkflowConfig
    from dragontools.worker.workflow_planning_service import WorkflowPlanningService

    calls = []

    class _Decision:
        last_selection = {
            "effective_preserve_dv": True,
            "effective_preserve_hdrplus": False,
            "generate_hdr10plus": False,
            "source_codec": "hevc",
        }

        def select_pipeline_context(self, input_path, media_info, override, **kwargs):
            calls.append(kwargs)
            return "dv", "mp4"

    logger = SimpleNamespace(
        file_start=lambda **_kw: None,
        info=lambda *_args: None,
        pipeline=lambda *_args: None,
    )
    planning = WorkflowPlanningService(
        config=WorkflowConfig(
            codec="h264", crf=22, preset="medium", scale_mode="original",
            encoder_options={"preserve_dv": True}, strip_only=False,
        ),
        runtime_state=SimpleNamespace(current_idx=1, total_count=1),
        logger=logger,
        pipeline_decision=_Decision(),
        encode_plan=SimpleNamespace(),
        standard_pipeline=SimpleNamespace(
            logger_start_params=lambda **_kw: ("cpu", 22, "CRF", "medium")
        ),
        output_paths=SimpleNamespace(
            resolve_output_path=lambda _path, _container, **_kw: (Path("."), "out.mp4")
        ),
    )
    planning.refresh_media_contract = lambda *_args, **_kwargs: None
    ctx = SimpleNamespace(
        input_path="film.mkv",
        analysis=_dv_media(),
        duration_ms=1000,
        plan=None,
    )

    planning.build_plan(ctx, {"processing_mode": "strip_only"})

    assert ctx.strip_only is True
    assert calls[0]["effective_codec"] == "h265"


def _postprocess_request() -> PipelineExecutionRequest:
    return PipelineExecutionRequest(
        pipeline="standard", input_path="in.mkv", output_path="out.mkv", container="mkv",
        media_info=SimpleNamespace(), plan=SimpleNamespace(), override={}, strip_only=False,
        duration_ms=1000, codec="h265", crf=22, preset="medium",
        generate_hdr10plus_postprocess=True,
    )


def test_missing_hdr10plus_postprocessor_preserves_successful_base_encode():
    from dragontools.worker.workflow_pipeline_executor import WorkflowPipelineExecutor

    success = PipelineExecutionResult.succeeded(sidecar_paths=("out.de.srt",))
    executor = WorkflowPipelineExecutor(
        standard_pipeline=SimpleNamespace(execute=lambda _request: success),
        strip_runner=lambda *_args: True,
        dv_pipeline=SimpleNamespace(),
        hdrplus_pipeline=SimpleNamespace(),
        temp_state=SimpleNamespace(reset_diagnostics=lambda: None),
    )

    result = executor.execute(_postprocess_request())

    assert result.success is False
    assert result.failure_stage == "HDR10+-Postprozess"
    assert result.preserve_failed_output is True
    assert result.sidecar_paths == ("out.de.srt",)


def test_hdr10plus_postprocessor_exception_preserves_successful_base_encode():
    from dragontools.worker.workflow_pipeline_executor import WorkflowPipelineExecutor

    success = PipelineExecutionResult.succeeded()

    def _boom(*_args, **_kwargs):
        raise RuntimeError("generator crash")

    executor = WorkflowPipelineExecutor(
        standard_pipeline=SimpleNamespace(execute=lambda _request: success),
        strip_runner=lambda *_args: True,
        dv_pipeline=SimpleNamespace(),
        hdrplus_pipeline=SimpleNamespace(generate_and_inject_existing_output=_boom),
        temp_state=SimpleNamespace(reset_diagnostics=lambda: None),
    )

    result = executor.execute(_postprocess_request())

    assert result.success is False
    assert "generator crash" in result.failure_reason
    assert result.preserve_failed_output is True


def test_assigned_encoder_profile_requests_hdr10plus_generator_capability_probe(monkeypatch):
    from dragontools.worker import converter_optional_runtime as optional_runtime

    calls = []

    class _Client:
        def __init__(self, executable, **_kwargs):
            calls.append(executable)

        def probe_version(self):
            return SimpleNamespace(success=True, version="1.2.3", error="", message="")

    worker = SimpleNamespace(
        _job_state=SimpleNamespace(
            file_overrides={
                "film.mkv": {
                    "encoder_profile": {
                        "codec": "h265",
                        "encoder_options": {"hdr10plus_generator_enabled": True},
                    }
                }
            }
        ),
        log=lambda *_args, **_kwargs: None,
    )
    tools = SimpleNamespace(
        hdr10plus_generator="generator.exe", ffmpeg="ffmpeg.exe", ffprobe="ffprobe.exe"
    )
    options = {"hdr10plus_generator_enabled": False}
    monkeypatch.setattr(optional_runtime, "generator_executable_available", lambda _path: True)
    monkeypatch.setattr(optional_runtime, "HDR10PlusGeneratorClient", _Client)

    optional_runtime._configure_hdr10plus_generator(worker, tools, options)

    assert calls == ["generator.exe"]
    assert options["_hdr10plus_generator_available"] is True
    assert options["_hdr10plus_generator_version"] == "1.2.3"


def test_strip_only_output_name_uses_actual_copied_video_codec(tmp_path):
    from dragontools.worker.output_path_service import OutputPathService, release_output_path_reservation

    source = tmp_path / "Film.mkv"
    source.write_bytes(b"source")
    service = OutputPathService(codec="h264", overwrite_original=False)
    _base, output = service.resolve_output_path(str(source), "mkv", codec="h265")
    try:
        assert Path(output).name == "Film_H265.mkv"
    finally:
        release_output_path_reservation(output)


def test_standard_pipeline_rejects_duplicate_video_mapping_before_ffmpeg(tmp_path):
    progress_calls = []
    runner = StandardPipelineRunner(
        tools=SimpleNamespace(ffmpeg="ffmpeg.exe"),
        codec="h265",
        crf=22,
        preset="medium",
        encoder_options={"encoder": "cpu"},
        progress_runner=lambda *_args, **_kwargs: progress_calls.append(True) or 0,
        subtitle_rules={},
    )
    request = PipelineExecutionRequest(
        pipeline="standard",
        input_path=str(tmp_path / "source.mkv"),
        output_path=str(tmp_path / "out.mkv"),
        container="mkv",
        media_info=SimpleNamespace(),
        plan=SimpleNamespace(
            vf_args=["-map", "0:v:0", "-map", "0:v:0"],
            audio_args=[], sn=[], audio_input_args=[], crop=None,
        ),
        override={}, strip_only=False, duration_ms=1000,
        codec="h265", crf=22, preset="medium", encoder_options={"encoder": "cpu"},
    )

    result = runner.execute(request)

    assert result.success is False
    assert result.failure_stage == "Standard-Encoding"
    assert "Video-Mapping" in result.failure_reason
    assert progress_calls == []


import pytest
from dragontools.rules.pipeline_selector import resolve_pipeline_context


@pytest.mark.parametrize(
    "source_codec,dv,hdrplus,target_codec,standard_container,dv_container,expected_pipeline,expected_container",
    [
        ("h264", False, False, "h264", "mkv", "mp4", "standard", "mkv"),
        ("hevc", False, False, "h265", "mp4", "mkv", "standard", "mp4"),
        ("hevc", False, True, "h265", "mkv", "mp4", "hdrplus", "mkv"),
        ("hevc", True, False, "h265", "mkv", "mp4", "dv", "mp4"),
        ("av1", False, False, "av1", "mkv", "mp4", "standard", "mkv"),
        ("av1", True, False, "av1", "mkv", "mp4", "av1_dv", "mp4"),
        ("av1", False, True, "av1", "mkv", "mp4", "av1_hdrplus", "mkv"),
        ("hevc", True, True, "h265", "mkv", "mp4", "dv", "mp4"),
    ],
)
def test_review24_dynamic_hdr_container_risk_matrix(
    source_codec, dv, hdrplus, target_codec, standard_container, dv_container,
    expected_pipeline, expected_container,
):
    video = VideoStream(
        index=0, codec=source_codec, width=3840, height=2160,
        hdr_format="dolby_vision" if dv else "hdr10plus" if hdrplus else None,
        has_dolby_vision=dv, has_hdr10plus=hdrplus,
    )
    media = MediaInfo(
        path="source.mkv", audio_streams=[], subtitle_streams=[], video_streams=[video],
        is_hdr=bool(dv or hdrplus), has_hdr10plus=hdrplus,
        dolby_vision=dv, dv_profile="10" if source_codec == "av1" and dv else "8" if dv else None,
        dv_profile_major=10 if source_codec == "av1" and dv else 8 if dv else None,
    )
    ctx = resolve_pipeline_context(
        media,
        codec=target_codec,
        global_preserve_dv=True,
        global_preserve_hdrplus=True,
        standard_container=standard_container,
        dv_container=dv_container,
    )
    assert str(getattr(ctx["pipeline"], "value", ctx["pipeline"])) == expected_pipeline
    assert ctx["container"] == expected_container
    assert ctx["should_archive"] is False


def test_profile_enabled_hdr10plus_generator_routes_preflight_to_generated_hdrplus():
    video = VideoStream(
        index=0, codec="hevc", width=3840, height=2160, bit_depth=10,
        color_transfer="smpte2084", color_primaries="bt2020", color_space="bt2020nc",
    )
    media = MediaInfo(
        path="hdr10.mkv", audio_streams=[], subtitle_streams=[], video_streams=[video], is_hdr=True,
    )
    override = {
        "encoder_profile": {
            "codec": "h265",
            "encoder_options": {"hdr10plus_generator_enabled": True},
        }
    }
    preview = build_rules_preview(
        "hdr10.mkv",
        codec="h265",
        file_override=override,
        media_info=media,
        default_encoder_options={
            "hdr10plus_generator_enabled": False,
            "_hdr10plus_generator_available": True,
        },
    )

    assert preview["effective_hdr10plus_generator_enabled"] is True
    assert preview["generate_hdr10plus"] is True
    assert preview["pipeline"] == "hdrplus"
