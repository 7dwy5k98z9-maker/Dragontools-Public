from __future__ import annotations

from types import SimpleNamespace


def _media(width: int, height: int):
    return SimpleNamespace(
        audio_streams=[],
        subtitle_streams=[],
        primary_video=SimpleNamespace(
            codec="h264",
            bit_depth=8,
            width=width,
            height=height,
        ),
        duration_s=10.0,
        is_hdr=False,
        has_dv=False,
        has_hdrplus=False,
        has_hdr10plus=False,
    )


def _contract(monkeypatch, *, width: int, height: int, scale: str, crop: str | None = None):
    import dragontools.worker.media_contract as module

    monkeypatch.setattr(module, "compute_audio_track_plan", lambda **_: [])
    monkeypatch.setattr(
        module,
        "compute_subtitle_plan",
        lambda *_, **__: SimpleNamespace(burn_sub=None, keep_streams=()),
    )
    return module.build_expected_media_contract(
        media_info=_media(width, height),
        file_override={},
        container="mkv",
        pipeline="standard",
        strip_only=False,
        effective_codec="h265",
        effective_preserve_hdrplus=False,
        subtitle_rules={},
        effective_scale_mode=scale,
        crop_filter=crop,
    )


def test_scale_filters_are_downscale_only():
    from dragontools.worker.encoder_args import _scale

    assert _scale("1080p") == r"scale=-2:min(1080\,ih)"
    assert _scale("720p") == r"scale=-2:min(720\,ih)"
    assert _scale("480p") == r"scale=-2:min(480\,ih)"
    assert _scale("4k") == r"scale=-2:min(2160\,ih)"
    assert _scale("original") is None


def test_1080p_downscales_4k_active_height(monkeypatch):
    contract = _contract(
        monkeypatch,
        width=3840,
        height=2160,
        scale="1080p",
        crop="crop=3840:1600:0:280",
    )
    assert contract.expected_height == 1080


def test_1080p_does_not_upscale_after_autocrop(monkeypatch):
    contract = _contract(
        monkeypatch,
        width=1920,
        height=1080,
        scale="1080p",
        crop="crop=1920:900:0:90",
    )
    assert contract.expected_height == 900


def test_1080p_does_not_upscale_small_source(monkeypatch):
    contract = _contract(
        monkeypatch,
        width=1280,
        height=720,
        scale="1080p",
        crop=None,
    )
    assert contract.expected_height == 720


def test_4k_does_not_upscale_1080p_source(monkeypatch):
    contract = _contract(
        monkeypatch,
        width=1920,
        height=1080,
        scale="4k",
        crop=None,
    )
    assert contract.expected_height == 1080


def test_dv_crop_replacement_preserves_escaped_scale_expression():
    from dragontools.worker.dv_crop_reconcile import replace_crop_in_vf_args

    args = [
        "-map", "0:v:0",
        "-vf", r"crop=3840:1600:0:280,scale=-2:min(1080\,ih)",
    ]
    result = replace_crop_in_vf_args(
        args,
        "crop=3840:1600:0:280",
        "crop=3840:900:0:630",
    )
    assert result[-1] == r"crop=3840:900:0:630,scale=-2:min(1080\,ih)"


def test_dv_adapter_exposes_final_rpu_reconciled_crop():
    from dragontools.worker.dv_runtime_models import DVTempState
    from dragontools.worker.dv_workflow_pipeline_adapter import DVPipelineExecutorAdapter
    from dragontools.worker.workflow_models import PipelineExecutionRequest

    class Pipeline:
        last_sidecar_paths = []
        last_failure_reason = ""
        last_failure_stage = ""
        last_tool_output = ""
        last_effective_crop = "crop=3840:900:0:630"

        def configure_encoder(self, _config):
            pass

        def run(self, **_kwargs):
            return True

    request = PipelineExecutionRequest(
        pipeline="dv",
        input_path="in.mkv",
        output_path="out.mkv",
        container="mkv",
        media_info=SimpleNamespace(),
        plan=SimpleNamespace(
            vf_args=[], audio_args=[], audio_input_args=[], sn=[],
            burn_sub_or_vf=False, crop="crop=3840:1600:0:280",
        ),
        override={},
        strip_only=False,
        duration_ms=1000,
        codec="h265",
        crf=22,
        preset="medium",
        encoder_options={"encoder": "cpu"},
        preserve_hdrplus=False,
    )

    result = DVPipelineExecutorAdapter(Pipeline(), DVTempState()).execute(request)

    assert result.success is True
    assert result.effective_crop_known is True
    assert result.effective_crop == "crop=3840:900:0:630"


def test_workflow_refreshes_contract_with_final_dv_crop():
    from dragontools.worker.workflow_models import PipelineExecutionResult, WorkflowConfig
    from dragontools.worker.workflow_services import WorkflowServices

    final_crop = "crop=3840:900:0:630"

    class Executor:
        def execute(self, _request):
            return PipelineExecutionResult.succeeded().__class__(
                success=True,
                effective_crop=final_crop,
                effective_crop_known=True,
            )

    refreshed: list[str | None] = []

    class Planning:
        def refresh_media_contract(self, _ctx, _override, *, crop_filter):
            refreshed.append(crop_filter)

    svc = WorkflowServices.__new__(WorkflowServices)
    svc._config = WorkflowConfig(
        codec="h265", crf=22, preset="medium", scale_mode="1080p",
        encoder_options={}, strip_only=False,
    )
    svc._pipeline_executor = Executor()
    svc._planning = Planning()
    svc._temp_state = SimpleNamespace(failure_reason="", failure_stage="", stderr="")
    svc._logger = SimpleNamespace(info=lambda _msg: None, error=lambda _msg: None)

    ctx = SimpleNamespace(
        pipeline="dv",
        input_path="in.mkv",
        output_path="out.mkv",
        container="mkv",
        analysis=SimpleNamespace(has_dv=True),
        plan=SimpleNamespace(),
        strip_only=False,
        duration_ms=1000,
        effective_codec="h265",
        effective_crf=22,
        effective_preset="medium",
        effective_encoder_options={},
        effective_preserve_hdrplus=False,
    )

    svc.process(ctx, {})

    assert refreshed == [final_crop]
