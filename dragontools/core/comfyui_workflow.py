# -*- coding: utf-8 -*-
"""Model-neutral ComfyUI workflow loading and placeholder preparation."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping


_ALLOWED_PLACEHOLDERS = {
    "INPUT_VIDEO",
    "OUTPUT_VIDEO",
    "FFMPEG",
    "INPUT_DIR",
    "OUTPUT_DIR",
    "OUTPUT_PREFIX",
    "PEAK_NITS",
    "MODEL_ROOT",
    "CHECKPOINT",
    "START_INDEX",
    "BATCH_SIZE",
    "DECODE_ARGS_JSON",
    "ENCODE_ARGS_JSON",
    "HDR_ARGS_JSON",
    "FPS_NUM",
    "FPS_DEN",
    "EXPECTED_FRAMES",
    "MANIFEST_PATH",
}

# DragonTools' full-file ComfyUI service can only consume workflows that are
# wired to the current source/output dynamically.  In particular, a frontend
# workflow containing ``LoadImage -> banner.png`` is a valid ComfyUI prompt in
# isolation, but it is not a valid DragonTools video workflow.
_VIDEO_REQUIRED_PLACEHOLDERS = (
    "INPUT_VIDEO",
    "OUTPUT_VIDEO",
    "MANIFEST_PATH",
)


def load_comfyui_api_workflow(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    payload = json.loads(source.read_text(encoding="utf-8"))
    validate_comfyui_api_workflow(payload)
    return payload


def validate_comfyui_api_workflow(payload: object) -> None:
    if not isinstance(payload, dict) or not payload:
        raise ValueError("ComfyUI API workflow must be a non-empty JSON object")
    for node_id, node in payload.items():
        if not isinstance(node_id, str) or not isinstance(node, dict):
            raise ValueError("ComfyUI API workflow nodes must use string ids and object values")
        if not str(node.get("class_type") or "").strip():
            raise ValueError(f"ComfyUI node {node_id!r} has no class_type")
        inputs = node.get("inputs")
        if inputs is not None and not isinstance(inputs, dict):
            raise ValueError(f"ComfyUI node {node_id!r} inputs must be an object")


def validate_comfyui_video_workflow(
    payload: object,
    *,
    required_class_types: Iterable[str] = (),
) -> None:
    """Validate the additional contract required by DragonTools video jobs.

    A generic ComfyUI API prompt is not automatically suitable for DragonTools.
    The full-file worker must receive the current input/output paths and write the
    progress/result manifest.  Static media loader nodes (for example a saved
    ``LoadImage`` node pointing at ``banner.png``) are rejected before they can
    reach ComfyUI and fail with ``Media input missing``.
    """

    validate_comfyui_api_workflow(payload)
    if not isinstance(payload, dict):
        raise ValueError("ComfyUI API workflow must be a JSON object")

    for node_id, node in payload.items():
        class_type = str(node.get("class_type") or "").strip()
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        if class_type.lower() in {"loadimage", "loadimagemask"}:
            media_value = str(inputs.get("image") or "").strip()
            if media_value and not _contains_placeholder(media_value):
                raise ValueError(
                    f"ComfyUI-Node {node_id!r} ({class_type}) verweist auf die statische Mediendatei "
                    f"{media_value!r}. DragonTools benötigt einen Voll-Datei-API-Workflow mit "
                    "{{INPUT_VIDEO}} statt eines Load-Image-Testbilds."
                )

    class_types = {
        str(node.get("class_type") or "").strip()
        for node in payload.values()
        if isinstance(node, dict)
    }
    required = tuple(str(item).strip() for item in required_class_types if str(item).strip())
    missing_classes = tuple(item for item in required if item not in class_types)
    if missing_classes:
        raise ValueError(
            "DragonTools-ComfyUI-Workflow enthält nicht die benötigten Node-Klassen: "
            + ", ".join(missing_classes)
        )

    missing_placeholders = tuple(
        name for name in _VIDEO_REQUIRED_PLACEHOLDERS
        if not workflow_uses_placeholder(payload, name)
    )
    if missing_placeholders:
        raise ValueError(
            "DragonTools-ComfyUI-Workflow fehlt/fehlen Pflicht-Platzhalter: "
            + ", ".join("{{" + name + "}}" for name in missing_placeholders)
        )


def workflow_uses_placeholder(payload: object, name: str) -> bool:
    token = "{{" + str(name or "").strip().upper() + "}}"
    if token == "{{}}":
        return False
    return _value_contains_token(payload, token)


def render_comfyui_workflow(template: Mapping[str, Any], values: Mapping[str, object]) -> dict[str, Any]:
    validate_comfyui_api_workflow(dict(template))
    normalized = {str(key).strip().upper(): value for key, value in values.items()}
    unknown = set(normalized) - _ALLOWED_PLACEHOLDERS
    if unknown:
        raise ValueError(f"Unsupported ComfyUI placeholder(s): {', '.join(sorted(unknown))}")
    return _render_value(dict(template), normalized)


def _render_value(value: Any, values: Mapping[str, object]) -> Any:
    if isinstance(value, dict):
        return {key: _render_value(item, values) for key, item in value.items()}
    if isinstance(value, list):
        return [_render_value(item, values) for item in value]
    if isinstance(value, str):
        rendered = value
        for key, replacement in values.items():
            token = "{{" + key + "}}"
            if rendered == token and not isinstance(replacement, str):
                return replacement
            rendered = rendered.replace(token, str(replacement))
        return rendered
    return value


def _value_contains_token(value: object, token: str) -> bool:
    if isinstance(value, dict):
        return any(_value_contains_token(item, token) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_value_contains_token(item, token) for item in value)
    return isinstance(value, str) and token in value


def _contains_placeholder(value: str) -> bool:
    text = str(value or "")
    return "{{" in text and "}}" in text


__all__ = [
    "load_comfyui_api_workflow",
    "render_comfyui_workflow",
    "validate_comfyui_api_workflow",
    "validate_comfyui_video_workflow",
    "workflow_uses_placeholder",
]
