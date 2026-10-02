from __future__ import annotations

import inspect
from types import SimpleNamespace

from dragontools.core.models import TargetCodec
from dragontools.core.sdr_hdr_enhancement import (
    SdrHdrEnhancementConfig,
    build_sdr_to_hdr_filters,
)
from dragontools.worker.dv_pipeline_context import DVRunRequest
from dragontools.worker.dv_pipeline_runtime import DVPreflightService
from dragontools.worker.dv_runtime_models import DVEncoderConfig
from dragontools.worker import dv_video_stage_service


def _request_p5() -> DVRunRequest:
    return DVRunRequest(
        input_path="input.mkv",
        output_path="output.mkv",
        media_info=SimpleNamespace(),
        vf_args=[],
        audio_args=[],
        audio_input_args=[],
        sn=[],
        crop=None,
        override={},
        preserve_hdrplus=False,
        generate_hdr10plus=False,
        container="mkv",
        profile_major=5,
    )


def test_sdr_hdr_libplacebo_uses_planar_10bit_for_cpu() -> None:
    filters = build_sdr_to_hdr_filters(
        SdrHdrEnhancementConfig(enabled=True),
        {"encoder": "cpu"},
    )
    assert filters[0].startswith("libplacebo=format=yuv420p10le:")
    assert "p010le" not in filters[0]


def test_sdr_hdr_libplacebo_keeps_p010_for_hardware_encoders() -> None:
    config = SdrHdrEnhancementConfig(enabled=True)
    for encoder in ("nvenc", "qsv", "amf"):
        filters = build_sdr_to_hdr_filters(config, {"encoder": encoder})
        assert filters[0].startswith("libplacebo=format=p010le:")


def test_dv5_preflight_log_reports_effective_cpu_pixel_format() -> None:
    verbose: list[str] = []
    service = DVPreflightService(
        tools=SimpleNamespace(ffmpeg="ffmpeg.exe"),
        log=lambda *_args: None,
        verbose_log=verbose.append,
        libplacebo_available=lambda: True,
    )
    result = service.validate(
        encoder_config=DVEncoderConfig(
            codec=TargetCodec.H265,
            crf=22,
            preset="medium",
            options={"encoder": "cpu"},
        ),
        request=_request_p5(),
    )
    assert result == (True, "", "")
    assert any("yuv420p10le" in line for line in verbose)
    assert not any(" / p010le / " in line for line in verbose)


def test_dv5_stage_log_is_not_hard_coded_to_p010() -> None:
    source = inspect.getsource(dv_video_stage_service.DVVideoStageService.encode_video)
    assert "encoder_10bit_filter_pixel_format" in source
    assert "ICtCp → BT.2020nc/PQ/{pixel_format}" in source
    assert "ICtCp → BT.2020nc/PQ/p010le" not in source
