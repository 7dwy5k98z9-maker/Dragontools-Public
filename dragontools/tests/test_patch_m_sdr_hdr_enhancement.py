from __future__ import annotations

from types import SimpleNamespace

from dragontools.core.models import MediaInfo, VideoStream
from dragontools.core.sdr_hdr_enhancement import (
    SdrHdrEnhancementConfig,
    build_sdr_to_hdr_filters,
    decide_sdr_hdr_enhancement,
    source_is_supported_sdr_bt709,
)
from dragontools.worker.encode_plan_service import EncodePlanService
from dragontools.worker.media_contract import build_expected_media_contract
from dragontools.worker.quality_target_service import AutomaticQualityTargetService
from dragontools.worker.standard_pipeline_runner import StandardPipelineRunner
from dragontools.worker.workflow_models import PipelineExecutionRequest


def _media(*, hdr=False, primaries="bt709", transfer="bt709", matrix="bt709"):
    video = VideoStream(
        index=0, codec="h264", width=1920, height=1080,
        hdr_format="hdr10" if hdr else None,
        pix_fmt="yuv420p10le" if hdr else "yuv420p",
        bit_depth=10 if hdr else 8,
        color_space="bt2020nc" if hdr else matrix,
        color_transfer="smpte2084" if hdr else transfer,
        color_primaries="bt2020" if hdr else primaries,
    )
    return MediaInfo(
        path="in.mkv", audio_streams=[], subtitle_streams=[], video_streams=[video],
        duration_s=120.0, is_hdr=hdr,
        transfer_characteristics="smpte2084" if hdr else transfer,
        matrix_coefficients="bt2020nc" if hdr else matrix,
    )


class _Logger:
    def info(self, *_args):
        pass


class _Streams:
    def __init__(self):
        self.post_filters = []
    def sub_args(self, *_args):
        return [], ["-sn"]
    def build_vf_args(self, _input, _output, _mi, _burn, pre_filters, post_filters=None):
        self.post_filters = list(post_filters or [])
        filters = list(pre_filters) + self.post_filters
        return ["-map", "0:v:0"] + (["-vf", ",".join(filters)] if filters else [])
    def audio_args(self, *_args):
        return ["-an"]
    def audio_input_args(self, *_args):
        return []


def _plan_service(streams):
    return EncodePlanService(
        codec="h265", encoder_options={}, scale_mode="original",
        detect_imax_auto=lambda *_: False, detect_crop=lambda *_: None,
        probe_duration_ms=lambda *_: 120000, stream_args_helper=streams,
        log=lambda *_: None, logger=_Logger(),
    )


def test_supported_source_requires_explicit_bt709_tags():
    assert source_is_supported_sdr_bt709(_media())[0] is True
    ok, reason = source_is_supported_sdr_bt709(_media(primaries=None))
    assert ok is False
    assert "Primär" in reason
    assert source_is_supported_sdr_bt709(_media(hdr=True))[0] is False


def test_supported_source_prefers_explicit_matrix_over_generic_yuv_color_space():
    media = _media(matrix="bt709")
    media.primary_video.color_space = "YUV"
    media.matrix_coefficients = "BT.709"
    ok, reason = source_is_supported_sdr_bt709(media)
    assert ok is True
    assert "eindeutig erkannt" in reason


def test_generic_yuv_color_space_is_not_misread_as_matrix_when_matrix_missing():
    media = _media(matrix="bt709")
    media.primary_video.color_space = "YUV"
    media.matrix_coefficients = None
    assert source_is_supported_sdr_bt709(media)[0] is True


def test_explicit_non_bt709_matrix_is_still_rejected():
    media = _media(matrix="bt709")
    media.primary_video.color_space = "YUV"
    media.matrix_coefficients = "BT.601"
    ok, reason = source_is_supported_sdr_bt709(media)
    assert ok is False
    assert "Matrix" in reason


def test_decision_applies_only_with_libplacebo_and_h265_or_av1():
    options = {"sdr_hdr_enabled": True, "_sdr_hdr_libplacebo_available": True}
    result = decide_sdr_hdr_enhancement(_media(), target_codec="h265", encoder_options=options)
    assert result.applied is True
    assert "inverse_tonemapping=1" in ",".join(result.filter_chain)
    assert decide_sdr_hdr_enhancement(_media(), target_codec="h264", encoder_options=options).applied is False
    missing = decide_sdr_hdr_enhancement(
        _media(), target_codec="h265",
        encoder_options={"sdr_hdr_enabled": True, "_sdr_hdr_libplacebo_available": False},
    )
    assert missing.applied is False
    assert "libplacebo" in missing.reason


def test_filter_is_p010_bt2020_pq_and_clamps_contrast():
    config = SdrHdrEnhancementConfig.from_encoder_options({
        "sdr_hdr_enabled": True, "sdr_hdr_contrast_recovery": 99,
    })
    assert config.contrast_recovery == 3.0
    chain = ",".join(build_sdr_to_hdr_filters(config))
    assert "format=p010le" in chain
    assert "color_primaries=bt2020" in chain
    assert "color_trc=smpte2084" in chain
    assert "gamut_mode=perceptual" in chain
    assert "contrast_recovery=3.00" in chain


def test_encode_plan_adds_enhancement_after_normal_pre_filters_and_marks_options():
    streams = _Streams()
    options = {
        "encoder": "nvenc", "sdr_hdr_enabled": True,
        "_sdr_hdr_libplacebo_available": True, "sdr_hdr_contrast_recovery": 0.3,
    }
    plan = _plan_service(streams).prepare_encode_plan(
        "in.mkv", "out.mkv", _media(), "standard", "mkv", {},
        encoder_options=options, codec="h265",
    )
    assert options["_sdr_hdr_applied"] is True
    assert options["_force_10bit"] is True
    assert any("inverse_tonemapping=1" in item for item in streams.post_filters)
    assert "libplacebo" in " ".join(plan.vf_args)


def test_existing_hdr_never_runs_sdr_hdr_enhancement():
    streams = _Streams()
    options = {"sdr_hdr_enabled": True, "_sdr_hdr_libplacebo_available": True}
    _plan_service(streams).prepare_encode_plan(
        "in.mkv", "out.mkv", _media(hdr=True), "standard", "mkv", {},
        encoder_options=options, codec="h265",
    )
    assert options["_sdr_hdr_applied"] is False
    assert not any("inverse_tonemapping" in item for item in streams.post_filters)


def test_standard_runner_forced_enhancement_sets_hdr10_output_metadata_and_10bit():
    commands = []
    runner = StandardPipelineRunner(
        tools=SimpleNamespace(ffmpeg="ffmpeg"), codec="h265", crf=23, preset="medium",
        encoder_options={"encoder": "cpu"},
        progress_runner=lambda cmd, *_: commands.append(cmd) or 0, log=lambda *_: None,
    )
    request = PipelineExecutionRequest(
        pipeline="standard", input_path="in.mkv", output_path="out.mkv", container="mkv",
        media_info=_media(),
        plan=SimpleNamespace(vf_args=["-map", "0:v:0"], audio_args=["-an"], audio_input_args=[], sn=["-sn"]),
        override={}, strip_only=False, duration_ms=1000, codec="h265", crf=23, preset="medium",
        encoder_options={"encoder": "cpu", "_sdr_hdr_applied": True},
    )
    assert runner.execute(request).success is True
    cmd = commands[0]
    assert cmd[cmd.index("-color_trc") + 1] == "smpte2084"
    assert cmd[cmd.index("-color_primaries") + 1] == "bt2020"
    assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p10le"
    assert "hdr10=1" in cmd[cmd.index("-x265-params") + 1]


def test_media_contract_requires_hdr10_depth_for_enhanced_output():
    contract = build_expected_media_contract(
        media_info=_media(), file_override={}, container="mkv", pipeline="standard",
        strip_only=False, effective_codec="h265", effective_preserve_hdrplus=False,
        subtitle_rules={}, force_hdr_output=True, effective_scale_mode="original",
    )
    assert contract.require_hdr is True
    assert contract.min_video_bit_depth == 10
    assert contract.require_dolby_vision is False
    assert contract.require_hdr10plus is False


class _NeverRunner:
    def run(self, *_args, **_kwargs):
        raise AssertionError("VMAF runner must not execute while SDR→HDR enhancement is active")


def test_vmaf_target_is_skipped_when_enhancement_will_apply():
    service = AutomaticQualityTargetService(
        tools=SimpleNamespace(ffmpeg="ffmpeg", ffprobe="ffprobe"),
        process_runner=_NeverRunner(), metrics=SimpleNamespace(), log=lambda *_: None,
        is_aborted=lambda: False,
    )
    result = service.resolve(
        input_path="in.mkv", media_info=_media(), codec="h265", fixed_quality=23,
        preset="p6", scale_mode="original",
        encoder_options={
            "encoder": "nvenc", "quality_target_enabled": True,
            "sdr_hdr_enabled": True, "_sdr_hdr_libplacebo_available": True,
        },
    )
    assert result.applied is False
    assert "SDR→HDR" in result.reason


def test_runtime_probe_requires_successful_libplacebo_initialization(monkeypatch):
    import dragontools.worker.sdr_hdr_runtime as runtime
    runtime.ffmpeg_has_libplacebo.cache_clear()
    seen = []

    def fake_run(cmd, **_kwargs):
        seen.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(runtime.subprocess, "run", fake_run)
    assert runtime.ffmpeg_has_libplacebo("ffmpeg-test") is True
    assert "inverse_tonemapping=1" in seen[0][seen[0].index("-vf") + 1]

    runtime.ffmpeg_has_libplacebo.cache_clear()
    monkeypatch.setattr(
        runtime.subprocess, "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout="", stderr="VK_ERROR"),
    )
    assert runtime.ffmpeg_has_libplacebo("ffmpeg-test") is False
