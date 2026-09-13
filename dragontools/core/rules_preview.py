from __future__ import annotations

from typing import Any

from .encoder_profile_override import effective_encoder_settings
from .media_analyzer import analyze_media
from .models import normalize_override_dict
from .paths import ToolPaths, get_tool_paths
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
from ..rules.pipeline_selector import resolve_pipeline_context


def build_rules_preview(
    file_path: str,
    *,
    codec: str = "h265",
    file_override: dict[str, Any] | None = None,
    planned_target=None,
    subtitle_rules: dict[str, Any] | None = None,
    tools: ToolPaths | None = None,
    media_info=None,
    global_preserve_dv: bool = True,
    global_preserve_hdrplus: bool = True,
    default_crf: int = 23,
    default_preset: str = "medium",
    default_scale_mode: str = "original",
    default_encoder_options: dict[str, Any] | None = None,
    autocrop_enabled: bool = False,
) -> dict[str, Any]:
    """Reine Preview aus Analyse- und Regelbausteinen; keine Worker-/FFmpeg-Ausführung."""
    resolved_tools = tools or get_tool_paths()
    mi = media_info if media_info is not None else analyze_media(file_path, resolved_tools)
    ov = normalize_override_dict(file_override)
    encoder_settings = effective_encoder_settings(
        default_codec=codec,
        default_crf=int(default_crf),
        default_preset=str(default_preset or "medium"),
        default_scale_mode=str(default_scale_mode or "original"),
        default_encoder_options=dict(default_encoder_options or {}),
        file_override=ov,
    )
    target_video = _build_target_video_preview(mi, ov, encoder_settings, autocrop_enabled=autocrop_enabled)
    pipeline_ctx = resolve_pipeline_context(
        mi,
        codec=codec,
        file_override=ov,
        global_preserve_dv=bool(global_preserve_dv),
        global_preserve_hdrplus=bool(global_preserve_hdrplus),
    )
    pipeline = str(_value(pipeline_ctx["pipeline"]))
    container = str(_value(pipeline_ctx["container"]))
    target = planned_target_dir(planned_target)

    return {
        "file_path": file_path,
        "codec": codec,
        "video": _build_video_preview(mi),
        "analysis_source": getattr(mi, "analysis_source", "Unbekannt"),
        "analysis_warnings": list(getattr(mi, "analysis_warnings", []) or []),
        "pipeline": pipeline,
        "target_container": container,
        "dv_preserved": pipeline in {"dv", "av1_dv"},
        "hdr10plus_preserved": pipeline in {"hdrplus", "av1_hdrplus"},
        "effective_preserve_dv": bool(pipeline_ctx.get("effective_preserve_dv")),
        "effective_preserve_hdrplus": bool(pipeline_ctx.get("effective_preserve_hdrplus")),
        "source_codec": str(pipeline_ctx.get("source_codec") or ""),
        "should_archive": bool(pipeline_ctx.get("should_archive")),
        "archive_reason": pipeline_ctx.get("archive_reason"),
        "ignored_hdr": list(pipeline_ctx.get("ignored_hdr") or []),
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
