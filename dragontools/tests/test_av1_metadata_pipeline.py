from __future__ import annotations

from types import SimpleNamespace

from dragontools.core.models import MediaInfo, VideoStream
from dragontools.worker.av1_metadata_pipeline import AV1DolbyVisionPipeline, AV1HDR10PlusPipeline
from dragontools.worker.dv_runtime_models import DVTempState
from dragontools.worker.media_contract import build_expected_media_contract
from dragontools.worker.workflow_models import PipelineExecutionRequest


class _Tools:
    ffmpeg = "ffmpeg"
    ffprobe = "ffprobe"
    mediainfo = "mediainfo"


class _Progress:
    def __init__(self):
        self.commands = []

    def __call__(self, cmd, _input, _duration):
        self.commands.append(list(cmd))
        return 0


def _media(*, dv=False, hdrplus=False, profile=10, source_codec="av1"):
    video = VideoStream(
        index=0, codec=source_codec, width=3840, height=2160,
        hdr_format="dolby_vision" if dv else "hdr10plus" if hdrplus else "hdr10",
        has_dolby_vision=dv, has_hdr10plus=hdrplus, bit_depth=10,
        color_transfer="smpte2084", color_primaries="bt2020",
    )
    return MediaInfo(
        path="in.mkv", audio_streams=[], subtitle_streams=[], video_streams=[video],
        is_hdr=True, has_hdr10plus=hdrplus, dolby_vision=dv,
        dolby_vision_profile=str(profile) if dv else None,
        dv_profile=str(profile) if dv else None,
        dv_profile_major=profile if dv else None,
    )


def _request(media, *, pipeline, encoder="cpu", vf_args=None, crop=None, container="mkv"):
    plan = SimpleNamespace(
        crop=crop, vf_args=list(vf_args or ["-map", "0:v:0"]), audio_args=[],
        audio_input_args=[], sn=[], burn_sub_or_vf=None,
    )
    return PipelineExecutionRequest(
        pipeline=pipeline, input_path="in.mkv", output_path=f"out.{container}",
        container=container, media_info=media, plan=plan, override={}, strip_only=False,
        duration_ms=1000, codec="av1", crf=28, preset="6",
        encoder_options={"encoder": encoder}, preserve_hdrplus=pipeline == "av1_hdrplus",
    )


def test_av1_dv_builds_native_svt_profile10_command(monkeypatch):
    progress = _Progress()
    runner = AV1DolbyVisionPipeline(tools=_Tools(), progress_runner=progress, temp_state=DVTempState())
    monkeypatch.setattr(runner, "_ffmpeg_help_contains", lambda *_: (True, "dolbyvision"))
    monkeypatch.setattr(
        "dragontools.worker.av1_metadata_pipeline.inspect_dynamic_hdr_with_mediainfo",
        lambda *_: SimpleNamespace(dolby_vision=True, dolby_vision_profile="10", hdr10plus=False),
    )
    result = runner.execute(_request(_media(dv=True, profile=8, source_codec="hevc"), pipeline="av1_dv"))
    assert result.success and result.verified_dolby_vision
    cmd = progress.commands[0]
    assert cmd[cmd.index("-c:v") + 1] == "libsvtav1"
    assert cmd[cmd.index("-dolbyvision") + 1] == "1"
    assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p10le"


def test_av1_dv_rejects_profile7_and_geometry_changes(monkeypatch):
    runner = AV1DolbyVisionPipeline(tools=_Tools(), progress_runner=_Progress(), temp_state=DVTempState())
    monkeypatch.setattr(runner, "_ffmpeg_help_contains", lambda *_: (True, "dolbyvision"))
    p7 = runner.execute(_request(_media(dv=True, profile=7, source_codec="hevc"), pipeline="av1_dv"))
    assert not p7.success and "Profil 7" in p7.failure_reason
    scaled = runner.execute(_request(_media(dv=True, profile=10), pipeline="av1_dv", vf_args=["-vf", "scale=-2:1080", "-map", "0:v:0"]))
    assert not scaled.success and "Crop oder Skalierung" in scaled.failure_reason


def test_av1_dv_rejects_burn_in(monkeypatch):
    runner = AV1DolbyVisionPipeline(tools=_Tools(), progress_runner=_Progress(), temp_state=DVTempState())
    monkeypatch.setattr(runner, "_ffmpeg_help_contains", lambda *_: (True, "dolbyvision"))
    request = _request(_media(dv=True, profile=10), pipeline="av1_dv")
    request.plan.burn_sub_or_vf = SimpleNamespace(index=2, language="de", forced=True)
    result = runner.execute(request)
    assert not result.success
    assert "Burn-In" in result.failure_reason


def test_av1_dv_hardware_is_fail_closed():
    progress = _Progress()
    runner = AV1DolbyVisionPipeline(tools=_Tools(), progress_runner=progress, temp_state=DVTempState())
    result = runner.execute(_request(_media(dv=True), pipeline="av1_dv", encoder="nvenc"))
    assert not result.success
    assert "CPU/SVT-AV1" in result.failure_reason
    assert progress.commands == []


def test_av1_hdrplus_builds_libaom_t35_command(monkeypatch):
    progress = _Progress()
    runner = AV1HDR10PlusPipeline(tools=_Tools(), progress_runner=progress, temp_state=DVTempState())
    monkeypatch.setattr(runner, "_ffmpeg_help_contains", lambda *_: (True, "libaom-av1"))
    monkeypatch.setattr(
        "dragontools.worker.av1_metadata_pipeline.inspect_dynamic_hdr_with_mediainfo",
        lambda *_: SimpleNamespace(dolby_vision=False, dolby_vision_profile=None, hdr10plus=True),
    )
    result = runner.execute(_request(_media(hdrplus=True, source_codec="hevc"), pipeline="av1_hdrplus"))
    assert result.success and result.verified_hdr10plus
    cmd = progress.commands[0]
    assert cmd[cmd.index("-c:v") + 1] == "libaom-av1"
    assert cmd[cmd.index("-b:v") + 1] == "0"
    assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p10le"
    assert "bt2020" in cmd and "smpte2084" in cmd


def test_av1_hdrplus_hardware_is_fail_closed():
    progress = _Progress()
    runner = AV1HDR10PlusPipeline(tools=_Tools(), progress_runner=progress, temp_state=DVTempState())
    result = runner.execute(_request(_media(hdrplus=True), pipeline="av1_hdrplus", encoder="nvenc"))
    assert not result.success
    assert "CPU/libaom-av1" in result.failure_reason
    assert progress.commands == []


def test_media_contract_requires_av1_dynamic_metadata_and_10bit():
    dv = build_expected_media_contract(
        media_info=_media(dv=True), file_override={}, container="mp4", pipeline="av1_dv",
        strip_only=False, effective_codec="av1", effective_preserve_hdrplus=False,
        subtitle_rules={}, effective_scale_mode="original", crop_filter=None,
    )
    assert dv.require_dolby_vision and dv.min_video_bit_depth == 10 and dv.require_hdr
    hp = build_expected_media_contract(
        media_info=_media(hdrplus=True), file_override={}, container="mkv", pipeline="av1_hdrplus",
        strip_only=False, effective_codec="av1", effective_preserve_hdrplus=True,
        subtitle_rules={}, effective_scale_mode="original", crop_filter=None,
    )
    assert hp.require_hdr10plus and hp.min_video_bit_depth == 10 and hp.require_hdr
