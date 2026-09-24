from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from dragontools.core.models import MediaInfo, VideoStream
from dragontools.core.sdr_hdr_enhancement import decide_sdr_hdr_enhancement
from dragontools.worker.comfyui_client import ComfyUIResult
from dragontools.worker.comfyui_video_worker import ComfyUIHDRVideoService


def _media(*, mode: str = "CFR", fps: str = "24000/1001") -> MediaInfo:
    video = VideoStream(
        index=0, codec="h264", width=1920, height=1080, pix_fmt="yuv420p",
        color_space="bt709", color_transfer="bt709", color_primaries="bt709",
        frame_rate=fps, frame_rate_mode=mode, frame_count=100,
    )
    return MediaInfo(path="source.mkv", audio_streams=[], subtitle_streams=[], video_streams=[video])


def _ready_options() -> dict:
    return {
        "sdr_hdr_enabled": True,
        "sdr_hdr_backend": "comfyui",
        "_comfyui_api_available": True,
        "_comfyui_model_assets_ready": True,
        "_comfyui_required_nodes_available": True,
        "_comfyui_workflow_valid": True,
    }


def test_comfyui_ready_is_now_applied_for_cfr_source():
    decision = decide_sdr_hdr_enhancement(_media(), target_codec="h265", encoder_options=_ready_options())
    assert decision.requested is True
    assert decision.applied is True
    assert "vollständige Datei" in decision.reason


def test_comfyui_vfr_is_not_applied_and_can_fall_back_to_sdr():
    decision = decide_sdr_hdr_enhancement(_media(mode="VFR"), target_codec="h265", encoder_options=_ready_options())
    assert decision.requested is True
    assert decision.applied is False
    assert "CFR" in decision.reason


def test_video_service_queues_full_file_workflow_and_reads_manifest(tmp_path: Path, monkeypatch):
    output = tmp_path / "HDR ä.mkv"
    manifest = tmp_path / "manifest.json"
    calls = []

    class FakeClient:
        def __init__(self, *_args, **_kwargs): pass
        def queue_workflow(self, workflow):
            calls.append(workflow)
            output.write_bytes(b"video")
            manifest.write_text(json.dumps({"success": True, "frames": 100, "elapsed_s": 2.5, "peak_vram_bytes": 1234}), encoding="utf-8")
            return ComfyUIResult(True, prompt_id="job-1")
        def history(self, prompt_id):
            return ComfyUIResult(True, payload={prompt_id: {"status": {"completed": True, "status_str": "success"}}})
        def cancel(self, prompt_id):
            return ComfyUIResult(True, prompt_id=prompt_id, message="cancelled")

    from dragontools.worker import comfyui_video_worker
    monkeypatch.setattr(comfyui_video_worker, "ComfyUIClient", FakeClient)
    repo = tmp_path / "HDRTVDM"
    method = repo / "method"
    method.mkdir(parents=True)
    checkpoint = method / "params_3DM.pth"
    checkpoint.write_bytes(b"x")
    options = {
        "comfyui_base_url": "http://127.0.0.1:8188",
        "_comfyui_model_profile": "hdrtvdm_lsn_3dm",
        "_comfyui_model_repository": str(repo),
        "_comfyui_model_checkpoint": str(checkpoint),
    }
    result = ComfyUIHDRVideoService(tools=SimpleNamespace(ffmpeg=r"C:\Tools\ffmpeg.exe")).render(
        input_path=r"D:\Input ä\film.mkv", output_path=str(output), media_info=_media(),
        encoder_options=options, decode_args=["-map", "0:v:0"],
        encode_args=["-c:v", "hevc_nvenc"], hdr_output_args=["-color_trc", "smpte2084"],
        manifest_path=str(manifest),
    )
    assert result.success is True
    assert result.frames == 100
    workflow = calls[0]
    assert workflow["2"]["inputs"]["input_video"] == r"D:\Input ä\film.mkv"
    assert json.loads(workflow["2"]["inputs"]["decode_args_json"]) == ["-map", "0:v:0"]
    assert workflow["2"]["inputs"]["fps_num"] == 24000


def test_video_service_cancels_exact_prompt_on_abort(tmp_path: Path, monkeypatch):
    cancelled = []

    class FakeClient:
        def __init__(self, *_args, **_kwargs): pass
        def queue_workflow(self, workflow): return ComfyUIResult(True, prompt_id="job-abort")
        def history(self, prompt_id): return ComfyUIResult(True, payload={})
        def cancel(self, prompt_id):
            cancelled.append(prompt_id)
            return ComfyUIResult(True, prompt_id=prompt_id, message="cancelled")

    from dragontools.worker import comfyui_video_worker
    monkeypatch.setattr(comfyui_video_worker, "ComfyUIClient", FakeClient)
    worker = SimpleNamespace(abort_requested=True)
    result = ComfyUIHDRVideoService(tools=SimpleNamespace(ffmpeg="ffmpeg"), worker=worker).render(
        input_path="in.mkv", output_path=str(tmp_path / "out.mkv"), media_info=_media(),
        encoder_options={"_comfyui_model_profile": "hdrtvdm_lsn_3dm", "_comfyui_model_repository": "x", "_comfyui_model_checkpoint": "y"},
        decode_args=["-map", "0:v:0"], encode_args=["-c:v", "libx265"], hdr_output_args=[],
        manifest_path=str(tmp_path / "manifest.json"),
    )
    assert result.success is False and result.error == "ABORTED"
    assert cancelled == ["job-abort"]


def test_standard_runner_uses_comfyui_video_then_muxes_original_audio(tmp_path: Path, monkeypatch):
    from dragontools.worker import standard_pipeline_runner as module
    from dragontools.worker.comfyui_video_worker import ComfyUIVideoResult
    from dragontools.worker.standard_pipeline_runner import StandardPipelineRunner
    from dragontools.worker.workflow_models import PipelineExecutionRequest

    render_calls = []

    class FakeService:
        def __init__(self, **_kwargs): pass
        def render(self, **kwargs):
            render_calls.append(kwargs)
            Path(kwargs["output_path"]).write_bytes(b"hdr-video")
            return ComfyUIVideoResult(True, output_path=kwargs["output_path"], frames=100, elapsed_s=1.0)

    monkeypatch.setattr(module, "ComfyUIHDRVideoService", FakeService)
    commands = []
    output = tmp_path / "final.mkv"
    runner = StandardPipelineRunner(
        tools=SimpleNamespace(ffmpeg="ffmpeg"), codec="h265", crf=23, preset="medium",
        encoder_options={}, progress_runner=lambda cmd, *_: commands.append(cmd) or 0,
        log=lambda *_: None,
    )
    request = PipelineExecutionRequest(
        pipeline="standard", input_path="source.mkv", output_path=str(output), container="mkv",
        media_info=_media(),
        plan=SimpleNamespace(
            vf_args=["-map", "0:v:0", "-vf", "scale=1280:720"],
            audio_args=["-map", "0:1", "-c:a:0", "copy"], audio_input_args=[], sn=["-sn"],
        ),
        override={}, strip_only=False, duration_ms=1000, codec="h265", crf=23, preset="medium",
        encoder_options={"encoder": "cpu", "_sdr_hdr_applied": True, "sdr_hdr_backend": "comfyui"},
    )
    result = runner.execute(request)
    assert result.success is True
    assert len(render_calls) == 1
    assert render_calls[0]["decode_args"] == ["-map", "0:v:0", "-vf", "scale=1280:720"]
    assert len(commands) == 1
    mux = commands[0]
    assert mux[mux.index("-map") + 1] == "1:v:0"
    assert "-c:v" in mux and mux[mux.index("-c:v") + 1] == "copy"
    assert "source.mkv" in mux


def test_encode_plan_falls_back_to_sdr_when_comfyui_was_selected_but_unavailable():
    from dragontools.worker.encode_plan_service import EncodePlanService

    class Streams:
        def sub_args(self, *_args): return [], ["-sn"]
        def build_vf_args(self, *_args, **_kwargs): return ["-map", "0:v:0"]
        def audio_args(self, *_args): return ["-an"]
        def audio_input_args(self, *_args): return []

    logs = []
    service = EncodePlanService(
        codec="h265", encoder_options={}, scale_mode="original",
        detect_imax_auto=lambda *_: False, detect_crop=lambda *_: None,
        probe_duration_ms=lambda *_: 1000, stream_args_helper=Streams(),
        log=lambda message, level="info": logs.append((level, message)),
        logger=SimpleNamespace(info=lambda *_: None),
    )
    options = {
        "sdr_hdr_enabled": True, "sdr_hdr_backend": "comfyui",
        "_comfyui_api_available": False,
    }
    plan = service.prepare_encode_plan(
        "in.mkv", "out.mkv", _media(), "standard", "mkv", {},
        encoder_options=options, codec="h265",
    )
    assert plan is not None
    assert options["_sdr_hdr_applied"] is False
    assert any("Ausgabe bleibt SDR" in message for _level, message in logs)
    assert any("API ist nicht erreichbar" in message for _level, message in logs)


def test_encode_plan_logs_comfyui_instead_of_libplacebo_when_comfyui_is_applied():
    from dragontools.worker.encode_plan_service import EncodePlanService

    class Streams:
        def sub_args(self, *_args): return [], ["-sn"]
        def build_vf_args(self, *_args, **_kwargs): return ["-map", "0:v:0"]
        def audio_args(self, *_args): return ["-an"]
        def audio_input_args(self, *_args): return []

    logs = []
    service = EncodePlanService(
        codec="h265", encoder_options={}, scale_mode="original",
        detect_imax_auto=lambda *_: False, detect_crop=lambda *_: None,
        probe_duration_ms=lambda *_: 1000, stream_args_helper=Streams(),
        log=lambda message, level="info": logs.append((level, message)),
        logger=SimpleNamespace(info=lambda *_: None),
    )
    options = dict(_ready_options())
    plan = service.prepare_encode_plan(
        "in.mkv", "out.mkv", _media(), "standard", "mkv", {},
        encoder_options=options, codec="h265",
    )

    assert plan is not None
    assert options["_sdr_hdr_applied"] is True
    assert any("ComfyUI/HDRTVDM" in message for _level, message in logs)
    assert not any("libplacebo" in message for _level, message in logs)


def test_encode_plan_falls_back_to_sdr_when_bt709_colorimetry_is_missing():
    from dragontools.worker.encode_plan_service import EncodePlanService

    class Streams:
        def sub_args(self, *_args): return [], ["-sn"]
        def build_vf_args(self, *_args, **_kwargs): return ["-map", "0:v:0"]
        def audio_args(self, *_args): return ["-an"]
        def audio_input_args(self, *_args): return []

    media = _media()
    media.primary_video.color_primaries = None
    media.primary_video.color_transfer = None
    media.primary_video.color_space = "YUV"
    media.transfer_characteristics = None
    media.matrix_coefficients = None

    logs = []
    service = EncodePlanService(
        codec="h265", encoder_options={}, scale_mode="original",
        detect_imax_auto=lambda *_: False, detect_crop=lambda *_: None,
        probe_duration_ms=lambda *_: 1000, stream_args_helper=Streams(),
        log=lambda message, level="info": logs.append((level, message)),
        logger=SimpleNamespace(info=lambda *_: None),
    )
    options = dict(_ready_options())
    plan = service.prepare_encode_plan(
        "in.mkv", "out.mkv", media, "standard", "mkv", {},
        encoder_options=options, codec="h265",
    )
    assert plan is not None
    assert options["_sdr_hdr_applied"] is False
    assert any("Ausgabe bleibt SDR" in message for _level, message in logs)
    assert any("Primärfarben nicht eindeutig" in message for _level, message in logs)


def test_encode_plan_falls_back_to_sdr_when_colorimetry_explicitly_does_not_match_bt709():
    from dragontools.worker.encode_plan_service import EncodePlanService

    class Streams:
        def sub_args(self, *_args): return [], ["-sn"]
        def build_vf_args(self, *_args, **_kwargs): return ["-map", "0:v:0"]
        def audio_args(self, *_args): return ["-an"]
        def audio_input_args(self, *_args): return []

    media = _media()
    media.matrix_coefficients = "BT.601"
    logs = []
    service = EncodePlanService(
        codec="h265", encoder_options={}, scale_mode="original",
        detect_imax_auto=lambda *_: False, detect_crop=lambda *_: None,
        probe_duration_ms=lambda *_: 1000, stream_args_helper=Streams(),
        log=lambda message, level="info": logs.append((level, message)),
        logger=SimpleNamespace(info=lambda *_: None),
    )
    options = dict(_ready_options())
    plan = service.prepare_encode_plan(
        "in.mkv", "out.mkv", media, "standard", "mkv", {},
        encoder_options=options, codec="h265",
    )
    assert plan is not None
    assert options["_sdr_hdr_applied"] is False
    assert any("Ausgabe bleibt SDR" in message for _level, message in logs)
    assert any("Matrix nicht eindeutig" in message for _level, message in logs)


def test_video_service_rejects_frame_count_mismatch_and_removes_output(tmp_path: Path, monkeypatch):
    output = tmp_path / "wrong-count.mkv"
    manifest = tmp_path / "wrong-count.json"

    class FakeClient:
        def __init__(self, *_args, **_kwargs): pass
        def queue_workflow(self, workflow):
            output.write_bytes(b"video")
            manifest.write_text(json.dumps({"success": True, "frames": 99}), encoding="utf-8")
            return ComfyUIResult(True, prompt_id="job-count")
        def history(self, prompt_id):
            return ComfyUIResult(True, payload={prompt_id: {"status": {"completed": True, "status_str": "success"}}})
        def cancel(self, prompt_id):
            return ComfyUIResult(True, prompt_id=prompt_id)

    from dragontools.worker import comfyui_video_worker
    monkeypatch.setattr(comfyui_video_worker, "ComfyUIClient", FakeClient)
    result = ComfyUIHDRVideoService(tools=SimpleNamespace(ffmpeg="ffmpeg")).render(
        input_path="source.mkv", output_path=str(output), media_info=_media(),
        encoder_options={"_comfyui_model_profile": "hdrtvdm_lsn_3dm"},
        decode_args=["-map", "0:v:0"], encode_args=["-c:v", "libx265"], hdr_output_args=[],
        manifest_path=str(manifest),
    )
    assert result.success is False
    assert result.error == "FRAME_COUNT_MISMATCH"
    assert not output.exists()
