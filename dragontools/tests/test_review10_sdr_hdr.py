from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from dragontools.core.models import MediaInfo, VideoStream
from dragontools.worker.comfyui_client import ComfyUIResult
from dragontools.worker.comfyui_video_worker import ComfyUIHDRVideoService


def _media() -> MediaInfo:
    video = VideoStream(
        index=0, codec="h264", width=1920, height=1080, pix_fmt="yuv420p",
        color_space="bt709", color_transfer="bt709", color_primaries="bt709",
        frame_rate="24000/1001", frame_rate_mode="CFR", frame_count=10,
    )
    return MediaInfo(path="source.mkv", audio_streams=[], subtitle_streams=[], video_streams=[video])


def test_new_comfyui_job_cannot_accept_stale_output_or_manifest(tmp_path: Path, monkeypatch):
    output = tmp_path / "old.mkv"
    manifest = tmp_path / "old.json"
    output.write_bytes(b"stale-video")
    manifest.write_text(json.dumps({"success": True, "frames": 10}), encoding="utf-8")

    class FakeClient:
        def __init__(self, *_a, **_kw): pass
        def queue_workflow(self, _workflow):
            # The new job deliberately produces no output/manifest.
            assert not output.exists()
            assert not manifest.exists()
            return ComfyUIResult(True, prompt_id="new-job")
        def history(self, prompt_id):
            return ComfyUIResult(True, payload={prompt_id: {"status": {"completed": True, "status_str": "success"}}})
        def cancel(self, prompt_id):
            return ComfyUIResult(True, prompt_id=prompt_id)

    from dragontools.worker import comfyui_video_worker as module
    monkeypatch.setattr(module, "ComfyUIClient", FakeClient)
    result = ComfyUIHDRVideoService(tools=SimpleNamespace(ffmpeg="ffmpeg")).render(
        input_path="source.mkv", output_path=str(output), media_info=_media(),
        encoder_options={"_comfyui_model_profile": "hdrtvdm_lsn_3dm"},
        decode_args=["-map", "0:v:0"], encode_args=["-c:v", "libx265"], hdr_output_args=[],
        manifest_path=str(manifest),
    )
    assert result.success is False
    assert result.error == "OUTPUT_MISSING"
    assert not output.exists()


def test_history_failure_cancels_exact_job_and_retains_unconfirmed_output(tmp_path: Path, monkeypatch):
    output = tmp_path / "partial.mkv"
    manifest = tmp_path / "manifest.json"
    cancelled: list[str] = []

    class FakeClient:
        def __init__(self, *_a, **_kw): pass
        def queue_workflow(self, _workflow):
            output.write_bytes(b"partial")
            return ComfyUIResult(True, prompt_id="job-history")
        def history(self, _prompt_id):
            return ComfyUIResult(False, error="HISTORY_FAILED", message="temporary API failure")
        def cancel(self, prompt_id):
            cancelled.append(prompt_id)
            return ComfyUIResult(True, prompt_id=prompt_id, message="cancelled")

    from dragontools.worker import comfyui_video_worker as module
    monkeypatch.setattr(module, "ComfyUIClient", FakeClient)
    result = ComfyUIHDRVideoService(tools=SimpleNamespace(ffmpeg="ffmpeg")).render(
        input_path="source.mkv", output_path=str(output), media_info=_media(),
        encoder_options={"_comfyui_model_profile": "hdrtvdm_lsn_3dm"},
        decode_args=["-map", "0:v:0"], encode_args=["-c:v", "libx265"], hdr_output_args=[],
        manifest_path=str(manifest),
    )
    assert result.success is False
    assert result.error == "HISTORY_FAILED"
    assert cancelled == ["job-history"]
    assert result.preserve_artifacts is True
    assert output.read_bytes() == b"partial"
    assert Path(str(manifest) + ".cancel").is_file()


def test_workflow_renderer_rejects_unresolved_template_tokens():
    from dragontools.core.comfyui_workflow import render_comfyui_workflow

    template = {
        "1": {
            "class_type": "X",
            "inputs": {
                "input_video": "{{INPUT_VIDEO}}",
                "output_prefix": "{{OUTPUT_PREFIX}}",
            },
        }
    }
    import pytest
    with pytest.raises(ValueError, match="OUTPUT_PREFIX"):
        render_comfyui_workflow(template, {"INPUT_VIDEO": "D:/in.mkv"})
