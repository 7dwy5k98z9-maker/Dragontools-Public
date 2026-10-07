from __future__ import annotations

from typing import Any

from .encoder_profile_override import effective_encoder_settings
from .media_analyzer import analyze_media
from .models import normalize_override_dict
from .tool_paths import ToolPaths, get_tool_paths
from .type_utils import _safe_bool
from .rules_preview_audio import build_audio_preview as _build_audio_preview
from .rules_preview_common import enum_value as _value, lang as _lang
from .rules_preview_subtitles import (
    TEXT_TO_SRT_PREVIEW_CODECS,
    build_subtitle_preview as _build_subtitle_preview,
    native_srt_sidecar_indices as _native_srt_sidecar_indices,
    subtitle_entries as _subtitle_entries,
    subtitle_entry as _subtitle_entry,
)
from .rules_preview_video import (
    build_target_video_preview as _build_target_video_preview,
    build_video_preview as _build_video_preview,
    even_width_for_height as _even_width_for_height,
)
from ..rules.move_rules import planned_target_dir
from .rules_preview_context import build_sdr_hdr_preview, resolve_preview_pipeline


def build_rules_preview(
    file_path: str,
    *,
    codec: str = "h265",
    file_override: dict[str, Any] | None = None,
    planned_target=None,
    subtitle_rules: dict[str, Any] | None = None,
    tools: ToolPaths | None = None,
    media_info=None,
    global_preserve_dv: bool | None = None,
    global_preserve_hdrplus: bool | None = None,
    default_crf: int = 23,
    default_preset: str = "medium",
    default_scale_mode: str = "original",
    default_encoder_options: dict[str, Any] | None = None,
    autocrop_enabled: bool = False,
    standard_container: str = "mkv",
    dv_container: str = "mp4",
    hdr10plus_generator_enabled: bool | None = None,
    hdr10plus_generator_available: bool | None = None,
) -> dict[str, Any]:
    """Reine Preview aus Analyse- und Regelbausteinen; keine Worker-/FFmpeg-Ausführung."""
    resolved_tools = tools or get_tool_paths()
    mi = media_info if media_info is not None else analyze_media(file_path, resolved_tools)
    ov = normalize_override_dict(file_override)
    base_encoder_options = dict(default_encoder_options or {})
    if global_preserve_dv is None:
        global_preserve_dv = _safe_bool(base_encoder_options.get("preserve_dv", True), True)
    if global_preserve_hdrplus is None:
        global_preserve_hdrplus = _safe_bool(
            base_encoder_options.get("preserve_hdrplus", True), True
        )
    if hdr10plus_generator_enabled is None:
        hdr10plus_generator_enabled = _safe_bool(
            base_encoder_options.get("hdr10plus_generator_enabled", False), False
        )
    if hdr10plus_generator_available is None:
        hdr10plus_generator_available = _safe_bool(
            base_encoder_options.get("_hdr10plus_generator_available", False), False
        )
    encoder_settings = effective_encoder_settings(
        default_codec=codec,
        default_crf=int(default_crf),
        default_preset=str(default_preset or "medium"),
        default_scale_mode=str(default_scale_mode or "original"),
        default_encoder_options=base_encoder_options,
        file_override=ov,
    )
    effective_options = dict(encoder_settings.get("encoder_options") or {})
    sdr_hdr_preview = build_sdr_hdr_preview(mi, effective_options,
        str(encoder_settings["codec"]), strip_only=ov.get("processing_mode") == "strip_only")
    target_video = _build_target_video_preview(mi, ov, encoder_settings, autocrop_enabled=autocrop_enabled)
    pipeline_ctx = resolve_preview_pipeline(
        mi, ov, encoder_settings,
        global_preserve_dv=global_preserve_dv, global_preserve_hdrplus=global_preserve_hdrplus,
        standard_container=standard_container, dv_container=dv_container,
        hdr10plus_generator_enabled=hdr10plus_generator_enabled,
        hdr10plus_generator_available=hdr10plus_generator_available,
    )
    pipeline = str(_value(pipeline_ctx["pipeline"]))
    container = str(_value(pipeline_ctx["container"]))
    strip_only = ov.get("processing_mode") == "strip_only"
    target = planned_target_dir(planned_target)

    return {
        "file_path": file_path,
        "codec": codec,
        "video": _build_video_preview(mi),
        "analysis_source": getattr(mi, "analysis_source", "Unbekannt"),
        "analysis_warnings": list(getattr(mi, "analysis_warnings", []) or []),
        "pipeline": pipeline,
        "target_container": container,
        "dv_preserved": bool(mi.has_dv) if strip_only else pipeline in {"dv", "av1_dv"},
        "hdr10plus_preserved": bool(mi.has_hdrplus) if strip_only else bool(
            mi.has_hdrplus and pipeline_ctx.get("effective_preserve_hdrplus")
            and pipeline in {"dv", "hdrplus", "av1_hdrplus"}
        ),
        "effective_preserve_dv": bool(pipeline_ctx.get("effective_preserve_dv")),
        "effective_preserve_hdrplus": bool(pipeline_ctx.get("effective_preserve_hdrplus")),
        "per_file_generate_hdr10plus": pipeline_ctx.get("per_file_generate_hdr10plus"),
        "effective_hdr10plus_generator_enabled": bool(
            pipeline_ctx.get("effective_hdr10plus_generator_enabled")
        ),
        "hdr10plus_generator_available": bool(
            pipeline_ctx.get("hdr10plus_generator_available")
        ),
        "generate_hdr10plus": bool(pipeline_ctx.get("generate_hdr10plus")),
        **sdr_hdr_preview,
        "hdr10plus_generation_code": pipeline_ctx.get("hdr10plus_generation_code"),
        "hdr10plus_generation_reason": pipeline_ctx.get("hdr10plus_generation_reason"),
        "source_codec": str(pipeline_ctx.get("source_codec") or ""),
        "should_archive": bool(pipeline_ctx.get("should_archive")),
        "archive_reason": pipeline_ctx.get("archive_reason"),
        "ignored_hdr": list(pipeline_ctx.get("ignored_hdr") or []),
        "capability_warnings": list(pipeline_ctx.get("capability_warnings") or []),
        "policy_infos": list(pipeline_ctx.get("policy_infos") or []),
        "audio": _build_audio_preview(mi, ov, container),
        "subtitles": _build_subtitle_preview(mi, ov, subtitle_rules, pipeline, container),
        "encoder": encoder_settings,
        "target_video": target_video,
        "overrides": ov,
        "move": {
            "planned_target": target,
            "available": bool(target),
            "status": "planned" if target else "not_present",
        },
    }
