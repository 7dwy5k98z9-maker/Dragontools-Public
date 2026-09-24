from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from dragontools.core.comfyui_workflow import (
    load_comfyui_api_workflow,
    render_comfyui_workflow,
    validate_comfyui_api_workflow,
)
from dragontools.core.comfyui_hdr_models import (
    HDRTVDM_PROFILE,
    builtin_hdrtvdm_workflow,
    get_comfyui_hdr_profile,
    node_classes_available,
    required_node_classes,
    resolve_comfyui_model_assets,
)
from dragontools.core.sdr_hdr_enhancement import decide_sdr_hdr_enhancement
from dragontools.core.tool_paths import ToolPathSettingsProvider, ToolPaths
from dragontools.worker.comfyui_client import ComfyUIClient, normalize_comfyui_base_url


def _sdr_bt709_media():
    video = SimpleNamespace(color_primaries="bt709", color_transfer="bt709", color_space="bt709", frame_rate="24000/1001", frame_rate_mode="CFR")
    return SimpleNamespace(
        is_hdr=False,
        has_dv=False,
        has_hdrplus=False,
        has_hdr10plus=False,
        primary_video=video,
    )


def test_comfyui_url_normalization_is_localhost_friendly():
    assert normalize_comfyui_base_url("") == "http://127.0.0.1:8188"
    assert normalize_comfyui_base_url("127.0.0.1:8188/") == "http://127.0.0.1:8188"
    assert normalize_comfyui_base_url("http://localhost:8188/") == "http://localhost:8188"


def test_comfyui_health_parses_version_gpu_and_16gb_vram():
    seen = []

    def transport(method, url, payload, timeout):
        seen.append((method, url, payload, timeout))
        return 200, {
            "system": {"comfyui_version": "0.3.test"},
            "devices": [{"name": "NVIDIA GeForce RTX 4080", "vram_total": 16 * 1024**3}],
        }

    result = ComfyUIClient("http://127.0.0.1:8188", transport=transport).health()
    assert result.success is True
    assert result.version == "0.3.test"
    assert "RTX 4080" in result.device
    assert result.vram_total == 16 * 1024**3
    assert seen[0][0:2] == ("GET", "http://127.0.0.1:8188/system_stats")


def test_comfyui_queue_keeps_unicode_paths_inside_workflow_and_uses_prompt_api():
    calls = []

    def transport(method, url, payload, timeout):
        calls.append((method, url, payload))
        return 200, {"prompt_id": "job-ä-123"}

    workflow = {
        "1": {
            "class_type": "DragonFutureVideoInput",
            "inputs": {"path": r"D:\Filme mit Umlaut ä\Quelle.mkv"},
        }
    }
    result = ComfyUIClient("localhost:8188", transport=transport).queue_workflow(workflow, client_id="dragon")
    assert result.success is True
    assert result.prompt_id == "job-ä-123"
    assert calls[0][0:2] == ("POST", "http://localhost:8188/prompt")
    assert calls[0][2]["prompt"]["1"]["inputs"]["path"].endswith("Quelle.mkv")


def test_comfyui_cancel_targets_exact_job_not_global_interrupt():
    calls = []

    def transport(method, url, payload, timeout):
        calls.append((method, url, payload))
        return 200, {"cancelled": True}

    result = ComfyUIClient(transport=transport).cancel("prompt-42")
    assert result.success is True
    assert result.prompt_id == "prompt-42"
    assert calls == [("POST", "http://127.0.0.1:8188/api/jobs/prompt-42/cancel", {})]


def test_comfyui_unreachable_is_fail_closed():
    def transport(*_args):
        raise OSError("connection refused")

    result = ComfyUIClient(transport=transport).health()
    assert result.success is False
    assert result.error == "SERVICE_UNREACHABLE"


def test_api_workflow_loader_and_placeholders_are_model_neutral(tmp_path: Path):
    path = tmp_path / "Workflow mit Umlaut ä.json"
    path.write_text(json.dumps({
        "1": {
            "class_type": "FutureHDRNode",
            "inputs": {
                "input": "{{INPUT_VIDEO}}",
                "peak": "{{PEAK_NITS}}",
                "prefix": "{{OUTPUT_PREFIX}}_hdr",
            },
        }
    }), encoding="utf-8")
    workflow = load_comfyui_api_workflow(path)
    rendered = render_comfyui_workflow(workflow, {
        "INPUT_VIDEO": r"D:\Video ä\input.mkv",
        "PEAK_NITS": 1000,
        "OUTPUT_PREFIX": "dragon",
    })
    assert rendered["1"]["inputs"]["input"].endswith("input.mkv")
    assert rendered["1"]["inputs"]["peak"] == 1000
    assert rendered["1"]["inputs"]["prefix"] == "dragon_hdr"


def test_invalid_workflow_rejected_before_comfyui_execution():
    with pytest.raises(ValueError):
        validate_comfyui_api_workflow({"1": {"inputs": {}}})
    with pytest.raises(ValueError):
        render_comfyui_workflow({"1": {"class_type": "X", "inputs": {}}}, {"UNKNOWN": "x"})


def test_comfyui_backend_runs_only_when_api_model_nodes_workflow_and_cfr_are_ready():
    media = _sdr_bt709_media()
    unavailable = decide_sdr_hdr_enhancement(
        media,
        target_codec="h265",
        encoder_options={
            "sdr_hdr_enabled": True,
            "sdr_hdr_backend": "comfyui",
            "_comfyui_api_available": False,
        },
    )
    assert unavailable.requested is True and unavailable.applied is False
    assert "nicht erreichbar" in unavailable.reason

    prepared = decide_sdr_hdr_enhancement(
        media,
        target_codec="h265",
        encoder_options={
            "sdr_hdr_enabled": True,
            "sdr_hdr_backend": "comfyui",
            "_comfyui_api_available": True,
            "_comfyui_model_assets_ready": True,
            "_comfyui_required_nodes_available": True,
            "_comfyui_workflow_valid": True,
        },
    )
    assert prepared.requested is True and prepared.applied is True
    assert "vollständige Datei" in prepared.reason

    ffmpeg = decide_sdr_hdr_enhancement(
        media,
        target_codec="h265",
        encoder_options={
            "sdr_hdr_enabled": True,
            "sdr_hdr_backend": "ffmpeg",
            "_sdr_hdr_libplacebo_available": True,
            "_comfyui_api_available": False,
        },
    )
    assert ffmpeg.applied is True
    assert ffmpeg.filter_chain


class _Provider(ToolPathSettingsProvider):
    def __init__(self, root: Path):
        self.root = root

    def get_custom_dirs(self) -> list[Path]:
        return [self.root]

    def find_in_settings(self, tool_key: str, *exe_names: str) -> str | None:
        if tool_key != "comfyui":
            return None
        for name in exe_names:
            candidate = self.root / name
            if candidate.is_file():
                return str(candidate)
        return None


def test_comfyui_external_tool_entry_accepts_portable_main_py(tmp_path: Path):
    main_py = tmp_path / "main.py"
    main_py.write_text("# ComfyUI marker\n", encoding="utf-8")
    tools = ToolPaths(provider=_Provider(tmp_path))
    assert Path(tools.comfyui) == main_py


def test_hdrtvdm_is_the_recommended_4080_profile_and_uses_3dm_checkpoint():
    profile = get_comfyui_hdr_profile(HDRTVDM_PROFILE)
    assert profile is not None
    assert profile.repository_url == "https://github.com/AndreGuo/HDRTVDM"
    assert profile.checkpoint_relative == "method/params_3DM.pth"
    assert profile.output_transfer == "smpte2084"
    assert profile.output_primaries == "bt2020"


def test_hdrtvdm_assets_resolve_unicode_paths_and_prefer_3dm(tmp_path: Path):
    repo = tmp_path / "HDR Modell ä"
    method = repo / "method"
    method.mkdir(parents=True)
    (method / "network.py").write_text("class TriSegNet: pass\n", encoding="utf-8")
    preferred = method / "params_3DM.pth"
    preferred.write_bytes(b"checkpoint")
    (method / "params.pth").write_bytes(b"fallback")
    status = resolve_comfyui_model_assets(HDRTVDM_PROFILE, repository=repo, checkpoint="")
    assert status.ready is True
    assert Path(status.checkpoint) == preferred.resolve()


def test_hdrtvdm_assets_fail_closed_without_checkpoint(tmp_path: Path):
    repo = tmp_path / "HDRTVDM"
    (repo / "method").mkdir(parents=True)
    (repo / "method" / "network.py").write_text("# marker\n", encoding="utf-8")
    status = resolve_comfyui_model_assets(HDRTVDM_PROFILE, repository=repo, checkpoint="")
    assert status.ready is False
    assert "Checkpoint" in status.error


def test_builtin_hdrtvdm_workflow_streams_complete_video_without_frame_sequence():
    workflow = builtin_hdrtvdm_workflow()
    rendered = render_comfyui_workflow(workflow, {
        "MODEL_ROOT": r"C:\AI\HDRTVDM",
        "CHECKPOINT": r"C:\AI\HDRTVDM\method\params_3DM.pth",
        "INPUT_VIDEO": r"D:\Temp\SDR ä.mkv",
        "OUTPUT_VIDEO": r"D:\Temp\HDR ä.mkv",
        "FFMPEG": r"C:\Tools\ffmpeg.exe",
        "DECODE_ARGS_JSON": '["-map","0:v:0"]',
        "ENCODE_ARGS_JSON": '["-c:v","hevc_nvenc"]',
        "HDR_ARGS_JSON": '["-color_trc","smpte2084"]',
        "FPS_NUM": 24000,
        "FPS_DEN": 1001,
        "BATCH_SIZE": 1,
        "EXPECTED_FRAMES": 34047,
        "MANIFEST_PATH": r"D:\Temp\hdr_manifest.json",
    })
    assert rendered["2"]["class_type"] == "DragonHDRTVDMVideoConvert"
    assert rendered["2"]["inputs"]["fps_num"] == 24000
    assert rendered["2"]["inputs"]["batch_size"] == 1
    assert "INPUT_DIR" not in str(rendered)


def test_comfyui_object_info_contract_can_verify_required_hdrtvdm_nodes():
    required = required_node_classes(HDRTVDM_PROFILE)
    payload = {name: {"display_name": name} for name in required}
    ready, missing = node_classes_available(payload, required)
    assert ready is True and missing == ()
    payload.pop(required[-1])
    ready, missing = node_classes_available(payload, required)
    assert ready is False and missing == (required[-1],)


def test_comfyui_client_object_info_uses_official_registry_endpoint():
    calls = []

    def transport(method, url, payload, timeout):
        calls.append((method, url, payload))
        return 200, {"DragonHDRTVDMConvert": {}}

    result = ComfyUIClient(transport=transport).object_info()
    assert result.success is True
    assert "DragonHDRTVDMConvert" in result.payload
    assert calls == [("GET", "http://127.0.0.1:8188/object_info", None)]


def test_hdrtvdm_custom_node_bridge_is_shipped_without_third_party_weights():
    root = Path(__file__).resolve().parents[2]
    bridge = root / "extras" / "comfyui" / "DragonTools_HDRTVDM"
    assert (bridge / "nodes.py").is_file()
    source = (bridge / "nodes.py").read_text(encoding="utf-8")
    for node in required_node_classes(HDRTVDM_PROFILE):
        assert node in source
    assert not list(bridge.rglob("*.pth"))
    assert "DragonHDRTVDMVideoConvert" in source


def test_comfyui_model_missing_never_falls_through_as_applied():
    decision = decide_sdr_hdr_enhancement(
        _sdr_bt709_media(),
        target_codec="h265",
        encoder_options={
            "sdr_hdr_enabled": True,
            "sdr_hdr_backend": "comfyui",
            "_comfyui_api_available": True,
            "_comfyui_model_assets_ready": False,
            "_comfyui_model_error": "HDRTVDM-Checkpoint fehlt.",
        },
    )
    assert decision.requested is True
    assert decision.applied is False
    assert "Checkpoint" in decision.reason


def test_comfyui_runtime_marks_hdrtvdm_ready_only_with_api_assets_nodes_and_workflow(tmp_path: Path, monkeypatch):
    from dragontools.worker import comfyui_runtime
    from dragontools.worker.comfyui_client import ComfyUIResult

    repo = tmp_path / "HDRTVDM ä"
    method = repo / "method"
    method.mkdir(parents=True)
    (method / "network.py").write_text("class TriSegNet: pass\n", encoding="utf-8")
    (method / "params_3DM.pth").write_bytes(b"model")

    required = required_node_classes(HDRTVDM_PROFILE)

    class FakeClient:
        def __init__(self, *_args, **_kwargs): pass
        def health(self):
            return ComfyUIResult(True, version="test", device="NVIDIA GeForce RTX 4080", vram_total=16 * 1024**3)
        def object_info(self):
            return ComfyUIResult(True, payload={name: {} for name in required})

    monkeypatch.setattr(comfyui_runtime, "ComfyUIClient", FakeClient)
    monkeypatch.setattr(comfyui_runtime, "generator_executable_available", lambda _path: True)
    logs = []
    worker = SimpleNamespace(log=lambda message, level="info": logs.append((level, message)))
    tools = SimpleNamespace(comfyui=str(tmp_path / "ComfyUI" / "main.py"))
    options = {
        "comfyui_model_profile": HDRTVDM_PROFILE,
        "comfyui_model_root": str(repo),
        "comfyui_checkpoint": "",
        "comfyui_workflow_path": "",
        "comfyui_base_url": "http://127.0.0.1:8188",
    }
    comfyui_runtime.configure_comfyui_runtime(worker, tools, options)
    assert options["_comfyui_backend_ready"] is True
    assert options["_comfyui_model_assets_ready"] is True
    assert options["_comfyui_required_nodes_available"] is True
    assert options["_comfyui_workflow_valid"] is True
    assert "params_3DM.pth" in options["_comfyui_model_checkpoint"]
    assert any("HDRTVDM-Modell" in message for _, message in logs)
