from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from dragontools.core.hdr10plus_generation import (
    decide_hdr10plus_generation,
    source_is_hdr10_pq_compatible,
    validate_hdr10plus_json_payload,
)
from dragontools.core.models import MediaInfo, VideoStream
from dragontools.worker.av1_metadata_pipeline import AV1HDR10PlusPipeline
from dragontools.worker.dv_runtime_models import DVTempState
from dragontools.worker.hdr10plus_generator_client import HDR10PlusGeneratorClient
from dragontools.worker.hdr10plus_workflow_policy import should_postprocess_generated_hdr10plus
from dragontools.worker.hdrplus_conversion import HDRPlusConversionHelper
from dragontools.worker.hdrplus_pipeline_coordinator import HDRPlusPipelineCoordinator, HDRPlusPipelineHooks
from dragontools.worker.hdrplus_runtime_models import HDRPlusEncoderConfig, HDRPlusExecutionContext
from dragontools.worker.hdrplus_stream_service import HDRPlusStreamService
from dragontools.worker.tool_runner import ToolRunResult
from dragontools.worker.workflow_models import PipelineExecutionRequest


def _media(
    *,
    codec: str = "hevc",
    primaries: str | None = "bt2020",
    matrix: str | None = "bt2020nc",
    transfer: str | None = "smpte2084",
    bit_depth: int | None = 10,
    hdrplus: bool = False,
    index: int = 0,
    extra_video: bool = False,
) -> MediaInfo:
    videos = [
        VideoStream(
            index=index,
            codec=codec,
            width=3840,
            height=2160,
            hdr_format="hdr10plus" if hdrplus else "hdr10",
            has_hdr10plus=hdrplus,
            bit_depth=bit_depth,
            color_space=matrix,
            color_transfer=transfer,
            color_primaries=primaries,
        )
    ]
    if extra_video:
        videos.append(
            VideoStream(
                index=index + 1,
                codec=codec,
                width=1280,
                height=720,
                bit_depth=10,
                color_space="bt2020nc",
                color_transfer="smpte2084",
                color_primaries="bt2020",
            )
        )
    return MediaInfo(
        path="source.mkv",
        audio_streams=[],
        subtitle_streams=[],
        video_streams=videos,
        is_hdr=True,
        has_hdr10plus=hdrplus,
        transfer_characteristics=transfer,
        matrix_coefficients=matrix,
    )


def _valid_payload(frames: int = 2, scenes: int = 1) -> dict:
    scene_info = [
        {
            "SequenceFrameIndex": i,
            "SceneId": 0,
            "SceneFrameIndex": i,
            "NumberOfWindows": 1,
            "LuminanceParameters": {
                "AverageRGB": 100,
                "MaxScl": [100, 100, 100],
                "LuminanceDistributions": {
                    "DistributionIndex": [1, 5, 10, 25, 50, 75, 90, 95, 99],
                    "DistributionValues": [1, 2, 3, 4, 5, 6, 7, 8, 9],
                },
            },
        }
        for i in range(frames)
    ]
    return {
        "JSONInfo": {"HDR10plusProfile": "A", "Version": "1.0"},
        "SceneInfo": scene_info,
        "SceneInfoSummary": {
            "SceneFirstFrameIndex": [0] * scenes,
            "SceneFrameNumbers": [frames] if scenes == 1 else [frames // scenes] * scenes,
        },
    }


def _fake_exe(tmp_path: Path) -> Path:
    exe = tmp_path / "HDR Plus Generator.exe"
    exe.write_text("stub", encoding="utf-8")
    return exe


def test_pq_generation_rejects_missing_bt2020_primaries():
    media = _media(primaries=None)
    ok, reason = source_is_hdr10_pq_compatible(media)
    assert ok is False
    assert "BT.2020" in reason
    decision = decide_hdr10plus_generation(media, target_codec="h265", enabled=True, tool_available=True)
    assert decision.eligible is False
    assert decision.code == "SOURCE_NOT_BT2020"


def test_pq_generation_rejects_wrong_matrix_and_explicit_8bit():
    wrong_matrix = _media(matrix="bt709")
    ok, reason = source_is_hdr10_pq_compatible(wrong_matrix)
    assert ok is False and "Matrix" in reason
    assert decide_hdr10plus_generation(
        wrong_matrix, target_codec="h265", enabled=True, tool_available=True
    ).code == "SOURCE_MATRIX_UNEXPECTED"

    eight_bit = _media(bit_depth=8)
    ok, reason = source_is_hdr10_pq_compatible(eight_bit)
    assert ok is False and "10-Bit" in reason
    assert decide_hdr10plus_generation(
        eight_bit, target_codec="h265", enabled=True, tool_available=True
    ).code == "SOURCE_BIT_DEPTH_UNEXPECTED"


def test_generator_client_rejects_generic_non_hdr_json(tmp_path):
    exe = _fake_exe(tmp_path)
    source = tmp_path / "source.hevc"
    source.write_bytes(b"x")
    output = tmp_path / "hdr10plus.json"

    def run(command, **_kwargs):
        output.write_text('{"foo":"bar"}', encoding="utf-8")
        return ToolRunResult(
            command=list(command),
            returncode=0,
            stdout=json.dumps({"success": True, "frames": 2, "scenes": 1, "output": str(output)}),
        )

    result = HDR10PlusGeneratorClient(str(exe), run_tool_fn=run).analyze(source, output)
    assert result.success is False
    assert result.error == "OUTPUT_INVALID_HDR10PLUS"
    assert not output.exists()


def test_hdr10plus_json_validator_rejects_impossible_ranges_and_summary_mismatch():
    payload = _valid_payload(frames=2)
    payload["SceneInfo"][0]["LuminanceParameters"]["AverageRGB"] = 100_001
    ok, reason = validate_hdr10plus_json_payload(payload)
    assert ok is False and "AverageRGB" in reason

    payload = _valid_payload(frames=2)
    payload["SceneInfoSummary"]["SceneFrameNumbers"] = [3]
    ok, reason = validate_hdr10plus_json_payload(payload)
    assert ok is False and "SceneFrameNumbers" in reason


def test_generator_client_rejects_frame_and_output_path_contract_mismatch(tmp_path):
    exe = _fake_exe(tmp_path)
    source = tmp_path / "source.hevc"
    source.write_bytes(b"x")
    output = tmp_path / "hdr10plus.json"

    def mismatch_frames(command, **_kwargs):
        output.write_text(json.dumps(_valid_payload(frames=2)), encoding="utf-8")
        return ToolRunResult(
            command=list(command), returncode=0,
            stdout=json.dumps({"success": True, "frames": 3, "scenes": 1, "output": str(output)}),
        )

    result = HDR10PlusGeneratorClient(str(exe), run_tool_fn=mismatch_frames).analyze(source, output)
    assert result.success is False and result.error == "FRAME_COUNT_MISMATCH"

    def mismatch_path(command, **_kwargs):
        output.write_text(json.dumps(_valid_payload(frames=2)), encoding="utf-8")
        return ToolRunResult(
            command=list(command), returncode=0,
            stdout=json.dumps({"success": True, "frames": 2, "scenes": 1, "output": str(tmp_path / "other.json")}),
        )

    result = HDR10PlusGeneratorClient(str(exe), run_tool_fn=mismatch_path).analyze(source, output)
    assert result.success is False and result.error == "OUTPUT_PATH_MISMATCH"
    assert not output.exists()


def test_generator_cli_rejects_reliable_probe_vs_decode_frame_mismatch(tmp_path, capsys, monkeypatch):
    import sys
    generator_src = Path(__file__).resolve().parents[2] / "dragon_hdr10plus_generator" / "src"
    sys.path.insert(0, str(generator_src))
    import dragon_hdr10plus_generator.cli as cli
    from dragon_hdr10plus_generator.analyzer.decoder import VideoProbe
    from dragon_hdr10plus_generator.analyzer.scanner import FrameStatistics, ScanResult

    source = tmp_path / "source.mkv"
    source.write_bytes(b"x")
    output = tmp_path / "out.json"
    probe = VideoProbe(
        transfer="smpte2084",
        primaries="bt2020",
        pixel_format="yuv420p10le",
        bit_depth=10,
        frames=3,
        width=1920,
        height=1080,
        fps=24.0,
        codec="hevc",
        color_space="bt2020nc",
        frame_count_source="stream_nb_frames",
        frame_count_reliability="reported",
    )
    frame = FrameStatistics(
        index=0,
        max_scl_nits=(1.0, 1.0, 1.0),
        average_maxrgb_nits=1.0,
        p01_nits=1.0,
        p25_nits=1.0,
        p50_nits=1.0,
        p75_nits=1.0,
        p90_nits=1.0,
        p95_nits=1.0,
        p9998_nits=1.0,
        p9999_nits=1.0,
        below_100_nits_percent=100.0,
        histogram=(1.0, 0.0),
    )
    monkeypatch.setattr(cli, "probe_video", lambda *_a, **_k: probe)
    monkeypatch.setattr(cli, "scan_pq_video", lambda *_a, **_k: ScanResult((frame, frame), 256, 144))

    rc = cli.main(["analyze", "--input", str(source), "--output", str(output)])
    response = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert response["error"] == "FRAME_COUNT_MISMATCH"
    assert response["reported_frames"] == 3 and response["decoded_frames"] == 2
    assert not output.exists()


def test_hdrplus_context_deepcopies_nested_settings_and_does_not_default_container():
    nested = {"x": {"y": [1]}}
    override = {"audio": {"tracks": [1]}}
    encoder = HDRPlusEncoderConfig.create(codec="h265", crf=22, preset="medium", encoder_options=nested)
    context = HDRPlusExecutionContext.create(
        input_path="in.mkv", output_path="out.mkv", media_info=_media(),
        vf_args=[], audio_args=[], audio_input_args=[], subtitle_args=[], crop=None,
        container="", override=override, encoder=encoder,
    )
    nested["x"]["y"].append(2)
    override["audio"]["tracks"].append(2)
    assert context.encoder.encoder_options["x"]["y"] == [1]
    assert context.override["audio"]["tracks"] == [1]
    assert context.container == ""


def test_strip_only_postprocess_is_allowed_only_for_actual_hevc_source():
    common = dict(
        selection={}, strip_only=True, pipeline="standard", codec="h265",
        encoder_options={}, generate_hdr10plus=True,
    )
    assert should_postprocess_generated_hdr10plus(**common, source_codec="hevc") is True
    assert should_postprocess_generated_hdr10plus(**common, source_codec="h264") is False
    assert should_postprocess_generated_hdr10plus(**common, source_codec="av1") is False


def test_stream_service_maps_explicit_global_ffmpeg_stream_index(tmp_path):
    seen = {}
    output = tmp_path / "video.hevc"

    def run(cmd, **_kwargs):
        seen["cmd"] = list(cmd)
        output.write_bytes(b"v" * 2048)
        return True

    service = HDRPlusStreamService(ffmpeg_path="ffmpeg", log=lambda *_: None)
    assert service.extract_hevc_annexb("input.mkv", str(output), run_tool=run, stream_index=3)
    cmd = seen["cmd"]
    assert cmd[cmd.index("-map") + 1] == "0:3"


class _NoEncode:
    def encode(self, **_kwargs):
        raise AssertionError("encode must not run")


class _NoSidecars:
    def export_sidecars_result(self, **_kwargs):
        raise AssertionError("sidecar export must not run")


class _NoSubtitles:
    def prepare_internal_mp4_tracks(self, **_kwargs):
        return True, []


def _coordinator() -> HDRPlusPipelineCoordinator:
    return HDRPlusPipelineCoordinator(
        encode_service=_NoEncode(),
        subtitle_service=_NoSidecars(),
        subtitle_mux_service=_NoSubtitles(),
        subtitle_rules={},
        log=lambda *_: None,
    )


def _context(tmp_path: Path, *, output: Path | None = None, media=None, container="mkv", generate=True):
    output = output or (tmp_path / f"out.{container or 'bin'}")
    return HDRPlusExecutionContext.create(
        input_path=str(tmp_path / "source.mkv"),
        output_path=str(output),
        media_info=media or _media(),
        vf_args=[], audio_args=[], audio_input_args=[], subtitle_args=["-sn"], crop=None,
        container=container,
        override={},
        encoder=HDRPlusEncoderConfig.create(codec="h265", crf=22, preset="medium", encoder_options={}),
        generate_hdr10plus=generate,
    )


def test_preserve_mode_multivideo_skips_ambiguous_container_extract_and_uses_primary_global_index(tmp_path):
    coordinator = _coordinator()
    source = tmp_path / "source.mkv"
    source.write_bytes(b"src")
    media = _media(index=3, extra_video=True, hdrplus=True)
    context = _context(tmp_path, media=media, generate=False)
    calls = []

    def extract_annexb(_src, target, *, stream_index=None):
        calls.append(("annexb", stream_index))
        Path(target).write_bytes(b"h" * 2048)
        return True

    def extract_meta(src, target):
        calls.append(("meta", Path(src).suffix))
        Path(target).write_text(json.dumps(_valid_payload()), encoding="utf-8")
        return True

    from dragontools.worker.hdrplus_pipeline_coordinator import HDRPlusPipelinePaths
    paths = HDRPlusPipelinePaths.create(tmp_path / "work")
    paths.root.mkdir()
    hooks = HDRPlusPipelineHooks(
        extract_hevc_annexb=extract_annexb,
        extract_metadata=extract_meta,
        generate_metadata=lambda *_: True,
        inject_metadata=lambda *_: True,
        mux_output=lambda *_a, **_k: True,
        run_mux_tool=lambda *_a, **_k: True,
        verify_final=lambda *_: True,
        cleanup_tmp_sub=lambda *_: None,
    )
    assert coordinator._step_extract_metadata(context, paths, hooks) is True
    assert calls[0] == ("annexb", 3)
    assert calls[1][0] == "meta"
    assert all(call != ("meta", ".mkv") for call in calls)


def test_hdrplus_preflight_rejects_empty_container_fail_closed(tmp_path):
    coordinator = _coordinator()
    context = _context(tmp_path, container="")
    hooks = HDRPlusPipelineHooks(
        extract_hevc_annexb=lambda *_a, **_k: True,
        extract_metadata=lambda *_: True,
        generate_metadata=lambda *_: True,
        inject_metadata=lambda *_: True,
        mux_output=lambda *_a, **_k: True,
        run_mux_tool=lambda *_a, **_k: True,
        verify_final=lambda *_: True,
        cleanup_tmp_sub=lambda *_: None,
    )
    assert coordinator._preflight(context, hooks) is False


def test_generated_pipeline_injection_failure_archives_encoded_media_and_json(tmp_path):
    source = tmp_path / "source.mkv"
    source.write_bytes(b"src")
    output = tmp_path / "out.mkv"

    class Encode:
        def encode(self, *, encoded_hevc, **_kwargs):
            encoded_hevc.write_bytes(b"v" * 2048)
            return True

    coordinator = HDRPlusPipelineCoordinator(
        encode_service=Encode(), subtitle_service=_NoSidecars(), subtitle_mux_service=_NoSubtitles(),
        subtitle_rules={}, log=lambda *_: None,
    )
    context = _context(tmp_path, output=output, generate=True)

    def generate(_video, metadata):
        Path(metadata).write_text(json.dumps(_valid_payload()), encoding="utf-8")
        return True

    hooks = HDRPlusPipelineHooks(
        extract_hevc_annexb=lambda *_a, **_k: True,
        extract_metadata=lambda *_: True,
        generate_metadata=generate,
        inject_metadata=lambda *_: False,
        mux_output=lambda *_a, **_k: True,
        run_mux_tool=lambda *_a, **_k: True,
        verify_final=lambda *_: True,
        cleanup_tmp_sub=lambda *_: None,
    )
    outcome = coordinator.run(context, hooks)
    assert outcome.success is False
    assert outcome.failure_archive_path
    archive = Path(outcome.failure_archive_path)
    assert (archive / "encoded.hevc").stat().st_size >= 1024
    assert (archive / "hdr10plus.json").is_file()
    assert (archive / "recovery.json").is_file()


def test_postprocess_verification_failure_keeps_original_and_archives_candidate_and_json(tmp_path):
    source = tmp_path / "source.mkv"
    source.write_bytes(b"src")
    output = tmp_path / "out.mkv"
    original = b"ORIGINAL" * 512
    output.write_bytes(original)
    coordinator = _coordinator()
    context = _context(tmp_path, output=output, generate=True)

    def extract(_src, target, **_kwargs):
        Path(target).write_bytes(b"v" * 2048)
        return True

    def generate(_src, target):
        Path(target).write_text(json.dumps(_valid_payload()), encoding="utf-8")
        return True

    def inject(_video, _json, target):
        Path(target).write_bytes(b"i" * 2048)
        return True

    def mux(_video, _donor, target, **_kwargs):
        Path(target).write_bytes(b"candidate" * 512)
        return True

    hooks = HDRPlusPipelineHooks(
        extract_hevc_annexb=extract,
        extract_metadata=lambda *_: True,
        generate_metadata=generate,
        inject_metadata=inject,
        mux_output=mux,
        run_mux_tool=lambda *_a, **_k: True,
        verify_final=lambda *_: False,
        cleanup_tmp_sub=lambda *_: None,
    )
    outcome = coordinator.postprocess_existing_output(context, hooks)
    assert outcome.success is False
    assert outcome.preserve_failed_output is True
    assert output.read_bytes() == original
    archive = Path(outcome.failure_archive_path)
    assert archive.is_dir()
    assert (archive / "hdr10plus.json").is_file()
    assert any(p.name.startswith("candidate") for p in archive.iterdir())


def test_postprocess_success_replaces_original_only_after_verification(tmp_path):
    source = tmp_path / "source.mkv"
    source.write_bytes(b"src")
    output = tmp_path / "out.mkv"
    output.write_bytes(b"old" * 512)
    coordinator = _coordinator()
    context = _context(tmp_path, output=output, generate=True)
    events = []

    def extract(_src, target, **_kwargs):
        events.append("extract")
        Path(target).write_bytes(b"v" * 2048)
        return True

    def generate(_src, target):
        events.append("generate")
        Path(target).write_text(json.dumps(_valid_payload()), encoding="utf-8")
        return True

    def inject(_video, _json, target):
        events.append("inject")
        Path(target).write_bytes(b"i" * 2048)
        return True

    def mux(_video, _donor, target, **_kwargs):
        events.append("mux")
        Path(target).write_bytes(b"new" * 1024)
        return True

    def verify(candidate, _json):
        events.append("verify")
        assert output.read_bytes().startswith(b"old")
        assert Path(candidate).read_bytes().startswith(b"new")
        return True

    hooks = HDRPlusPipelineHooks(
        extract_hevc_annexb=extract,
        extract_metadata=lambda *_: True,
        generate_metadata=generate,
        inject_metadata=inject,
        mux_output=mux,
        run_mux_tool=lambda *_a, **_k: True,
        verify_final=verify,
        cleanup_tmp_sub=lambda *_: None,
    )
    outcome = coordinator.postprocess_existing_output(context, hooks, sidecar_paths=("a.srt",))
    assert outcome.success and outcome.verified_hdr10plus
    assert outcome.sidecar_paths == ("a.srt",)
    assert output.read_bytes().startswith(b"new")
    assert events == ["extract", "generate", "inject", "mux", "verify"]


def test_conversion_helper_exposes_workflow_postprocess_method():
    assert callable(getattr(HDRPlusConversionHelper, "generate_and_inject_existing_output", None))


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


def _av1_request(tmp_path: Path, media: MediaInfo, *, container="mkv"):
    plan = SimpleNamespace(crop=None, vf_args=["-map", "0:v:0"], audio_args=[], audio_input_args=[], sn=[], burn_sub_or_vf=None)
    return PipelineExecutionRequest(
        pipeline="av1_hdrplus", input_path=str(tmp_path / "in.mkv"), output_path=str(tmp_path / f"out.{container}"),
        container=container, media_info=media, plan=plan, override={}, strip_only=False,
        duration_ms=1000, codec="av1", crf=28, preset="6", encoder_options={"encoder": "cpu"},
        preserve_hdrplus=True,
    )


def test_av1_hdrplus_rejects_h264_source_and_geometry_change(tmp_path, monkeypatch):
    runner = AV1HDR10PlusPipeline(tools=_Tools(), progress_runner=_Progress(), temp_state=DVTempState())
    monkeypatch.setattr(runner, "_ffmpeg_help_contains", lambda *_: (True, "libaom"))
    h264 = runner.execute(_av1_request(tmp_path, _media(codec="h264", hdrplus=True)))
    assert not h264.success and "HEVC- oder AV1" in h264.failure_reason

    request = _av1_request(tmp_path, _media(codec="hevc", hdrplus=True))
    request.plan.vf_args = ["-vf", "scale=-2:1080", "-map", "0:v:0"]
    scaled = runner.execute(request)
    assert not scaled.success and "Crop oder Skalierung" in scaled.failure_reason


def test_av1_hdrplus_final_verification_failure_preserves_completed_output(tmp_path, monkeypatch):
    progress = _Progress()
    runner = AV1HDR10PlusPipeline(tools=_Tools(), progress_runner=progress, temp_state=DVTempState())
    monkeypatch.setattr(runner, "_ffmpeg_help_contains", lambda *_: (True, "libaom"))
    monkeypatch.setattr(
        "dragontools.worker.av1_metadata_pipeline.inspect_dynamic_hdr_with_mediainfo",
        lambda *_: SimpleNamespace(hdr10plus=False),
    )
    monkeypatch.setattr(runner, "_fallback_analysis", lambda *_: None)
    request = _av1_request(tmp_path, _media(codec="hevc", hdrplus=True))
    Path(request.input_path).write_bytes(b"input")
    result = runner.execute(request)
    assert result.success is False
    assert result.preserve_failed_output is True

