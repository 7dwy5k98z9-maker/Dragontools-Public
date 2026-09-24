from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from dragontools.core.comfyui_hdr_models import (
    HDRTVDM_PROFILE,
    required_node_classes,
    resolve_comfyui_workflow,
)
from dragontools.core.comfyui_workflow import validate_comfyui_video_workflow
from dragontools.core.models import MediaInfo, VideoStream
from dragontools.worker.comfyui_client import ComfyUIResult
from dragontools.worker.comfyui_video_worker import ComfyUIHDRVideoService


def _load_image_workflow() -> dict:
    return {
        "1": {
            "class_type": "LoadImage",
            "inputs": {"image": "banner.png"},
        }
    }


def _media() -> MediaInfo:
    video = VideoStream(
        index=0,
        codec="h264",
        width=1920,
        height=1080,
        pix_fmt="yuv420p",
        color_space="bt709",
        color_transfer="bt709",
        color_primaries="bt709",
        frame_rate="25",
        frame_rate_mode="CFR",
        frame_count=10,
    )
    return MediaInfo(path="source.mkv", audio_streams=[], subtitle_streams=[], video_streams=[video])


def test_static_load_image_workflow_is_not_a_dragontools_video_workflow():
    try:
        validate_comfyui_video_workflow(_load_image_workflow())
    except ValueError as exc:
        message = str(exc)
    else:  # pragma: no cover - explicit regression guard
        raise AssertionError("static LoadImage workflow must be rejected")

    assert "LoadImage" in message
    assert "banner.png" in message
    assert "{{INPUT_VIDEO}}" in message


def test_hdrtvdm_invalid_custom_media_workflow_falls_back_to_builtin(tmp_path: Path):
    workflow_path = tmp_path / "wrong-workflow.json"
    workflow_path.write_text(json.dumps(_load_image_workflow()), encoding="utf-8")

    selected = resolve_comfyui_workflow(HDRTVDM_PROFILE, workflow_path=workflow_path)

    assert selected.ready is True
    assert selected.source == "builtin"
    assert selected.workflow is not None
    assert selected.workflow["2"]["class_type"] == "DragonHDRTVDMVideoConvert"
    assert "LoadImage" in selected.warning
    assert "banner.png" in selected.warning
    assert all(
        node in {entry["class_type"] for entry in selected.workflow.values()}
        for node in required_node_classes(HDRTVDM_PROFILE)
    )


def test_video_service_never_queues_static_banner_workflow(tmp_path: Path, monkeypatch):
    wrong_workflow = tmp_path / "wrong-workflow.json"
    wrong_workflow.write_text(json.dumps(_load_image_workflow()), encoding="utf-8")
    output = tmp_path / "out.mkv"
    manifest = tmp_path / "manifest.json"
    queued_workflows: list[dict] = []
    logs: list[tuple[str, str]] = []

    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def queue_workflow(self, workflow):
            queued_workflows.append(workflow)
            output.write_bytes(b"video")
            manifest.write_text(json.dumps({"success": True, "frames": 10}), encoding="utf-8")
            return ComfyUIResult(True, prompt_id="job-safe")

        def history(self, prompt_id):
            return ComfyUIResult(
                True,
                payload={prompt_id: {"status": {"completed": True, "status_str": "success"}}},
            )

        def cancel(self, prompt_id):
            return ComfyUIResult(True, prompt_id=prompt_id)

    from dragontools.worker import comfyui_video_worker

    monkeypatch.setattr(comfyui_video_worker, "ComfyUIClient", FakeClient)
    result = ComfyUIHDRVideoService(
        tools=SimpleNamespace(ffmpeg="ffmpeg"),
        log=lambda message, level="info": logs.append((level, message)),
    ).render(
        input_path=str(tmp_path / "source.mkv"),
        output_path=str(output),
        media_info=_media(),
        encoder_options={
            "_comfyui_model_profile": HDRTVDM_PROFILE,
            "comfyui_workflow_path": str(wrong_workflow),
        },
        decode_args=["-map", "0:v:0"],
        encode_args=["-c:v", "libx265"],
        hdr_output_args=["-color_trc", "smpte2084"],
        manifest_path=str(manifest),
    )

    assert result.success is True
    assert queued_workflows
    queued = queued_workflows[0]
    assert not any(node.get("class_type") == "LoadImage" for node in queued.values())
    assert queued["2"]["class_type"] == "DragonHDRTVDMVideoConvert"
    assert queued["2"]["inputs"]["input_video"].endswith("source.mkv")
    assert any("eingebauten HDRTVDM-Voll-Datei-Workflow" in message for _level, message in logs)
