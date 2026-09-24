# -*- coding: utf-8 -*-
"""Model profiles and readiness checks for the optional ComfyUI SDR->HDR backend.

DragonTools does not vendor third-party model weights.  Profiles describe the
external assets and custom-node contract expected by the integration so missing
or incompatible installations fail closed without affecting FFmpeg workflows.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .comfyui_workflow import load_comfyui_api_workflow, validate_comfyui_video_workflow


HDRTVDM_PROFILE = "hdrtvdm_lsn_3dm"
CUSTOM_PROFILE = "custom"


@dataclass(frozen=True, slots=True)
class ComfyUIHDRModelProfile:
    key: str
    display_name: str
    repository_url: str
    checkpoint_relative: str
    fallback_checkpoint_relative: str = ""
    output_transfer: str = "smpte2084"
    output_primaries: str = "bt2020"
    required_nodes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ComfyUIModelAssets:
    ready: bool
    repository: str = ""
    checkpoint: str = ""
    error: str = ""


@dataclass(frozen=True, slots=True)
class ComfyUIWorkflowSelection:
    ready: bool
    workflow: dict[str, Any] | None = None
    source: str = ""
    configured_path: str = ""
    warning: str = ""
    error: str = ""


_PROFILES: dict[str, ComfyUIHDRModelProfile] = {
    HDRTVDM_PROFILE: ComfyUIHDRModelProfile(
        key=HDRTVDM_PROFILE,
        display_name="HDRTVDM LSN – params_3DM.pth (empfohlen)",
        repository_url="https://github.com/AndreGuo/HDRTVDM",
        checkpoint_relative="method/params_3DM.pth",
        fallback_checkpoint_relative="method/params.pth",
        required_nodes=(
            "DragonHDRTVDMModelLoader",
            "DragonHDRTVDMVideoConvert",
        ),
    ),
}


def available_comfyui_hdr_profiles() -> tuple[ComfyUIHDRModelProfile, ...]:
    return tuple(_PROFILES.values())


def get_comfyui_hdr_profile(key: str | None) -> ComfyUIHDRModelProfile | None:
    return _PROFILES.get(str(key or "").strip().lower())


def resolve_comfyui_model_assets(
    profile_key: str,
    *,
    repository: str | Path | None,
    checkpoint: str | Path | None,
) -> ComfyUIModelAssets:
    normalized_key = str(profile_key or "").strip().lower()
    if normalized_key == CUSTOM_PROFILE:
        return ComfyUIModelAssets(True)
    profile = get_comfyui_hdr_profile(normalized_key)
    if profile is None:
        return ComfyUIModelAssets(False, error="Unbekanntes ComfyUI-Modellprofil.")

    repo = Path(str(repository or "").strip()).expanduser() if str(repository or "").strip() else None
    if repo is None or not repo.is_dir():
        return ComfyUIModelAssets(False, repository=str(repo or ""), error="HDRTVDM-Repository fehlt.")
    if not (repo / "method" / "network.py").is_file():
        return ComfyUIModelAssets(False, repository=str(repo), error="HDRTVDM method/network.py wurde nicht gefunden.")

    explicit = str(checkpoint or "").strip()
    if explicit:
        explicit_path = Path(explicit).expanduser()
        if not explicit_path.is_absolute():
            explicit_path = repo / explicit_path
        candidates = [explicit_path]
    else:
        candidates = [repo / profile.checkpoint_relative]
    if not explicit and profile.fallback_checkpoint_relative:
        candidates.append(repo / profile.fallback_checkpoint_relative)
    model_path = next((item for item in candidates if item.is_file()), None)
    if model_path is None:
        expected = explicit or str(repo / profile.checkpoint_relative)
        return ComfyUIModelAssets(False, repository=str(repo), checkpoint=expected, error="HDRTVDM-Checkpoint fehlt.")

    return ComfyUIModelAssets(True, repository=str(repo.resolve()), checkpoint=str(model_path.resolve()))


def required_node_classes(profile_key: str) -> tuple[str, ...]:
    profile = get_comfyui_hdr_profile(profile_key)
    return profile.required_nodes if profile is not None else ()



def collect_comfyui_hdr_options(settings) -> dict[str, Any]:
    from .settings_access import settings_bool, settings_int, settings_text
    from .settings_conversion import (
        DEFAULT_COMFYUI_AUTO_START, DEFAULT_COMFYUI_BASE_URL, DEFAULT_COMFYUI_CHECKPOINT,
        DEFAULT_COMFYUI_MODEL_PROFILE, DEFAULT_COMFYUI_MODEL_ROOT, DEFAULT_COMFYUI_START_FILE,
        DEFAULT_COMFYUI_START_WAIT_SECONDS, DEFAULT_COMFYUI_WORKFLOW_PATH,
        SET_KEY_COMFYUI_AUTO_START, SET_KEY_COMFYUI_BASE_URL, SET_KEY_COMFYUI_CHECKPOINT,
        SET_KEY_COMFYUI_MODEL_PROFILE, SET_KEY_COMFYUI_MODEL_ROOT, SET_KEY_COMFYUI_START_FILE,
        SET_KEY_COMFYUI_START_WAIT_SECONDS, SET_KEY_COMFYUI_WORKFLOW_PATH,
    )
    return {
        "comfyui_base_url": settings_text(settings, SET_KEY_COMFYUI_BASE_URL, DEFAULT_COMFYUI_BASE_URL),
        "comfyui_workflow_path": settings_text(settings, SET_KEY_COMFYUI_WORKFLOW_PATH, DEFAULT_COMFYUI_WORKFLOW_PATH),
        "comfyui_model_profile": settings_text(settings, SET_KEY_COMFYUI_MODEL_PROFILE, DEFAULT_COMFYUI_MODEL_PROFILE),
        "comfyui_model_root": settings_text(settings, SET_KEY_COMFYUI_MODEL_ROOT, DEFAULT_COMFYUI_MODEL_ROOT),
        "comfyui_checkpoint": settings_text(settings, SET_KEY_COMFYUI_CHECKPOINT, DEFAULT_COMFYUI_CHECKPOINT),
        "comfyui_auto_start": settings_bool(settings, SET_KEY_COMFYUI_AUTO_START, DEFAULT_COMFYUI_AUTO_START),
        "comfyui_start_file": settings_text(settings, SET_KEY_COMFYUI_START_FILE, DEFAULT_COMFYUI_START_FILE),
        "comfyui_start_wait_seconds": settings_int(
            settings, SET_KEY_COMFYUI_START_WAIT_SECONDS, DEFAULT_COMFYUI_START_WAIT_SECONDS,
            minimum=5, maximum=180,
        ),
    }

def builtin_hdrtvdm_workflow() -> dict[str, Any]:
    """Executable full-file HDRTVDM workflow used by DragonTools.

    The model is kept in a separate loader node so ComfyUI can cache it across
    multiple files.  The video node streams decoded RGB frames through the
    model and directly into FFmpeg; no complete image sequence is materialized.
    """
    return {
        "1": {
            "class_type": "DragonHDRTVDMModelLoader",
            "inputs": {
                "repo_root": "{{MODEL_ROOT}}",
                "checkpoint": "{{CHECKPOINT}}",
                "device": "cuda",
                "precision": "fp16",
            },
        },
        "2": {
            "class_type": "DragonHDRTVDMVideoConvert",
            "inputs": {
                "model": ["1", 0],
                "input_video": "{{INPUT_VIDEO}}",
                "output_video": "{{OUTPUT_VIDEO}}",
                "ffmpeg_path": "{{FFMPEG}}",
                "decode_args_json": "{{DECODE_ARGS_JSON}}",
                "encode_args_json": "{{ENCODE_ARGS_JSON}}",
                "hdr_args_json": "{{HDR_ARGS_JSON}}",
                "fps_num": "{{FPS_NUM}}",
                "fps_den": "{{FPS_DEN}}",
                "batch_size": "{{BATCH_SIZE}}",
                "expected_frames": "{{EXPECTED_FRAMES}}",
                "manifest_path": "{{MANIFEST_PATH}}",
            },
        },
    }


def builtin_workflow_for_profile(profile_key: str) -> dict[str, Any] | None:
    if str(profile_key or "").strip().lower() == HDRTVDM_PROFILE:
        return builtin_hdrtvdm_workflow()
    return None




def resolve_comfyui_workflow(
    profile_key: str,
    *,
    workflow_path: str | Path | None = None,
) -> ComfyUIWorkflowSelection:
    """Resolve a DragonTools-compatible API workflow for the selected profile.

    A configured custom workflow is used only when it satisfies the full-file
    DragonTools video contract.  For the built-in HDRTVDM profile an invalid
    custom workflow falls back to the tested built-in streaming workflow.  This
    prevents stale ComfyUI frontend workflows such as ``LoadImage/banner.png``
    from being queued by DragonTools.
    """

    profile = str(profile_key or "").strip().lower()
    configured = str(workflow_path or "").strip()
    required = required_node_classes(profile)
    builtin = builtin_workflow_for_profile(profile)

    if configured:
        try:
            custom = load_comfyui_api_workflow(Path(configured))
            validate_comfyui_video_workflow(custom, required_class_types=required)
            return ComfyUIWorkflowSelection(
                True, custom, source="custom", configured_path=configured,
            )
        except Exception as exc:
            if builtin is None:
                return ComfyUIWorkflowSelection(
                    False, source="custom", configured_path=configured, error=str(exc),
                )
            validate_comfyui_video_workflow(builtin, required_class_types=required)
            return ComfyUIWorkflowSelection(
                True, builtin, source="builtin", configured_path=configured,
                warning=(
                    f"Konfigurierter ComfyUI-Workflow wird ignoriert ({exc}). "
                    "DragonTools verwendet den eingebauten HDRTVDM-Voll-Datei-Workflow."
                ),
            )

    if builtin is None:
        return ComfyUIWorkflowSelection(
            False, source="none", error="Kein API-Workflow für das gewählte Modellprofil konfiguriert.",
        )
    try:
        validate_comfyui_video_workflow(builtin, required_class_types=required)
    except Exception as exc:
        return ComfyUIWorkflowSelection(False, source="builtin", error=str(exc))
    return ComfyUIWorkflowSelection(True, builtin, source="builtin")


def node_classes_available(payload: Mapping[str, Any], required: tuple[str, ...]) -> tuple[bool, tuple[str, ...]]:
    missing = tuple(name for name in required if name not in payload)
    return not missing, missing


__all__ = [
    "CUSTOM_PROFILE", "HDRTVDM_PROFILE", "ComfyUIHDRModelProfile", "ComfyUIModelAssets",
    "ComfyUIWorkflowSelection",
    "available_comfyui_hdr_profiles", "builtin_hdrtvdm_workflow", "builtin_workflow_for_profile",
    "collect_comfyui_hdr_options",
    "get_comfyui_hdr_profile", "node_classes_available", "required_node_classes",
    "resolve_comfyui_model_assets", "resolve_comfyui_workflow",
]
