from __future__ import annotations

from typing import Any
from .media_analyzer import analyze_media
from .models import normalize_override_dict
from .paths import ToolPaths, get_tool_paths
from ..rules.move_rules import planned_target_dir
from ..rules.audio_rules import (
    normalize_audio_codec,
)
from ..rules.pipeline_selector import resolve_pipeline_context
from ..rules.subtitle_rules import (
    additional_sidecars_enabled,
    build_mp4_subtitle_storage_plan,
    compute_subtitle_plan,
    mp4_sidecars_enabled,
    text_to_srt_sidecar_enabled,
)


TEXT_TO_SRT_PREVIEW_CODECS = {
    "ass",
    "ssa",
    "subrip",
    "srt",
    "subt",
    "mov_text",
    "tx3g",
    "text",
    "webvtt",
}


def _lang(value: Any) -> str:
    text = (str(value).strip().lower() if value is not None else "")
    return text or "und"


def _subtitle_entry(stream) -> dict[str, Any]:
    return {
        "index": stream.index,
        "language": _lang(stream.language),
        "forced": bool(stream.forced),
        "codec": (stream.codec or "").lower(),
        "title": stream.title,
    }


def _subtitle_entries(streams) -> list[dict[str, Any]]:
    return [_subtitle_entry(stream) for stream in streams]


def _native_srt_sidecar_indices(streams) -> set[int]:
    return {
        int(stream.index)
        for stream in streams
        if str(getattr(stream, "codec", "") or "").lower() in {"subrip", "srt", "subt", "mov_text", "tx3g", "text"}
    }


def _build_audio_preview(mi, ov: dict[str, Any], container: str) -> dict[str, Any]:
    """
    Preview-Struktur für die Audio-Entscheidung.

    Nutzt denselben Entscheidungskern wie der produktive Worker und der
    DV-Worker (``rules.audio_plan``), damit Preview und tatsächlich
    erzeugte Audiospuren nicht auseinanderlaufen.
    """
    from ..rules.audio_plan import compute_audio_track_plan

    audio_mode = ov.get("audio_mode", "auto")
    fa = ((ov.get("_legacy") or {}).get("audio_action") or "auto")

    plan = compute_audio_track_plan(
        audio_streams=mi.audio_streams,
        file_override=ov,
        container=container,
    )

    result: list[dict[str, Any]] = []
    for decision in plan:
        chosen = decision.stream
        result.append(
            {
                "index": chosen.index,
                "language": _lang(chosen.language),
                "title": chosen.title,
                "source_codec": normalize_audio_codec(chosen.codec),
                "source_channels": chosen.channels,
                "source_bitrate": chosen.bitrate,
                "decision": "transcode" if decision.needs_transcode else "copy",
                "target_codec": decision.target_codec,
                "target_channels": decision.target_channels,
                "target_bitrate": decision.target_bitrate,
                "is_extra_stereo": decision.is_extra_stereo,
            }
        )

    return {
        "override_mode": audio_mode,
        "override_action": fa if audio_mode == "custom" and not ov.get("audio_tracks") else "auto",
        "source_count": len(mi.audio_streams),
        "selected_streams": result,
        "selection_count": len(result),
        "disabled": not bool(result),
    }


def _build_subtitle_preview(
    mi,
    ov: dict[str, Any],
    subtitle_rules: dict[str, Any] | None,
    pipeline: str,
    container: str,
) -> dict[str, Any]:
    plan = compute_subtitle_plan(
        mi.subtitle_streams,
        audio_streams=mi.audio_streams,
        file_override=ov,
        subtitle_rules=subtitle_rules,
        container_copy_supported=(pipeline not in {"dv", "av1_dv"}),
        media_duration_s=getattr(mi, "duration_s", None),
    )
    burn_sub = plan.burn_sub
    keep = list(plan.keep_streams)
    external_streams = list(plan.external_streams)
    target_container = str(container or "mkv").lower()
    mp4_export_enabled = target_container in {"mp4", "m4v", "mov"} and mp4_sidecars_enabled(subtitle_rules)
    additional_enabled = additional_sidecars_enabled(subtitle_rules)
    text_srt_enabled = text_to_srt_sidecar_enabled(subtitle_rules)
    copy_supported = pipeline not in {"dv", "av1_dv"}

    selected_for_sidecars = list(external_streams)
    if target_container in {"mp4", "m4v", "mov"}:
        storage = build_mp4_subtitle_storage_plan(
            plan,
            subtitle_rules=subtitle_rules,
            preserve_burn_candidate=False,
        )
        stream_copy_candidates = list(storage.internal_streams)
        normal_sidecar_streams = (
            selected_for_sidecars
            if (mp4_export_enabled or additional_enabled)
            else list(storage.external_streams)
        )
    elif not copy_supported:
        stream_copy_candidates = []
        normal_sidecar_streams = (
            selected_for_sidecars
            if (mp4_export_enabled or additional_enabled)
            else []
        )
    else:
        stream_copy_candidates = keep
        normal_sidecar_streams = selected_for_sidecars if additional_enabled else []

    normal_srt_indices = _native_srt_sidecar_indices(normal_sidecar_streams)
    text_srt_candidates = [
        s for s in selected_for_sidecars
        if str(getattr(s, "codec", "") or "").lower()
        in TEXT_TO_SRT_PREVIEW_CODECS
        and int(s.index) not in normal_srt_indices
    ]
    sidecar_fields = {
        "mp4_sidecars_enabled": mp4_export_enabled,
        "additional_sidecars_enabled": additional_enabled,
        "text_to_srt_sidecar_enabled": text_srt_enabled,
        "native_sidecar_candidates": _subtitle_entries(normal_sidecar_streams),
        "native_sidecar_candidate_count": len(normal_sidecar_streams),
        "text_to_srt_candidates": [
            _subtitle_entry(s)
            for s in text_srt_candidates
        ] if text_srt_enabled else [],
        "text_to_srt_candidate_count": len(text_srt_candidates) if text_srt_enabled else 0,
        "sidecar_export_enabled": bool(normal_sidecar_streams or (text_srt_enabled and text_srt_candidates)),
    }

    if pipeline in {"dv", "av1_dv"}:
        external_enabled = bool(sidecar_fields["sidecar_export_enabled"])
        return {
            "override_mode": plan.override_mode,
            "source_count": len(mi.subtitle_streams),
            "burn_in": burn_sub is not None,
            "burn_candidate": (
                {
                    "index": burn_sub.index,
                    "language": _lang(burn_sub.language),
                    "forced": bool(burn_sub.forced),
                    "codec": (burn_sub.codec or "").lower(),
                    "title": burn_sub.title,
                }
                if burn_sub is not None
                else None
            ),
            "burn_blocked_reason": plan.burn_blocked_reason,
            "burn_warnings": list(getattr(plan, "burn_warnings", ()) or ()),
            "burn_event_rate": getattr(plan, "burn_event_rate", None),
            "ambiguous_burn_candidates": [
                {
                    "index": stream.index,
                    "language": _lang(stream.language),
                    "forced": bool(stream.forced),
                    "codec": (stream.codec or "").lower(),
                    "title": stream.title,
                }
                for stream in plan.burn_candidates
            ],
            "container_copy_supported": False,
            "stream_copy_candidates": [],
            "copy_candidate_count": 0,
            "external_export_enabled": external_enabled,
            "external_export_candidates": _subtitle_entries(normal_sidecar_streams),
            "external_export_candidate_count": len(normal_sidecar_streams),
            **sidecar_fields,
        }

    return {
        "override_mode": plan.override_mode,
        "source_count": len(mi.subtitle_streams),
        "burn_in": burn_sub is not None,
        "burn_candidate": (
            {
                "index": burn_sub.index,
                "language": _lang(burn_sub.language),
                "forced": bool(burn_sub.forced),
                "codec": (burn_sub.codec or "").lower(),
                "title": burn_sub.title,
            }
            if burn_sub is not None
            else None
        ),
        "burn_blocked_reason": plan.burn_blocked_reason,
        "burn_warnings": list(getattr(plan, "burn_warnings", ()) or ()),
        "burn_event_rate": getattr(plan, "burn_event_rate", None),
        "ambiguous_burn_candidates": [
            {
                "index": stream.index,
                "language": _lang(stream.language),
                "forced": bool(stream.forced),
                "codec": (stream.codec or "").lower(),
                "title": stream.title,
            }
            for stream in plan.burn_candidates
        ],
        "container_copy_supported": True,
        "stream_copy_candidates": _subtitle_entries(stream_copy_candidates),
        "copy_candidate_count": len(stream_copy_candidates),
        **sidecar_fields,
    }


def _value(value: Any) -> Any:
    return getattr(value, "value", value)


def _build_video_preview(mi) -> dict[str, Any]:
    pv = mi.primary_video
    if pv is None:
        return {
            "available": False,
            "codec": "",
            "width": None,
            "height": None,
            "bit_depth": None,
            "pix_fmt": None,
            "is_hdr": bool(getattr(mi, "is_hdr", False)),
            "has_dv": bool(getattr(mi, "has_dv", False)),
            "dv_profile": getattr(mi, "dv_profile", None) or getattr(mi, "dolby_vision_profile", None),
            "has_hdr10plus": bool(getattr(mi, "has_hdrplus", False)),
            "hdr_format": None,
        }

    return {
        "available": True,
        "index": pv.index,
        "codec": (pv.codec or "").lower(),
        "width": pv.width,
        "height": pv.height,
        "bit_depth": pv.bit_depth,
        "pix_fmt": pv.pix_fmt,
        "is_hdr": bool(getattr(mi, "is_hdr", False)),
        "has_dv": bool(getattr(mi, "has_dv", False)),
        "dv_profile": getattr(mi, "dv_profile", None) or getattr(mi, "dolby_vision_profile", None),
        "has_hdr10plus": bool(getattr(mi, "has_hdrplus", False)),
        "hdr_format": pv.hdr_format,
        "color_space": pv.color_space,
        "color_transfer": pv.color_transfer,
        "color_primaries": pv.color_primaries,
    }


def build_rules_preview(
    file_path: str,
    *,
    codec: str = "h265",
    file_override: dict[str, Any] | None = None,
    planned_target = None,
    subtitle_rules: dict[str, Any] | None = None,
    tools: ToolPaths | None = None,
    media_info=None,
    global_preserve_dv: bool = True,
    global_preserve_hdrplus: bool = True,
) -> dict[str, Any]:
    """
    Baut eine reine Anzeige-/Preview-Struktur aus den vorhandenen Analyse- und Regelbausteinen.
    Keine ffmpeg-Args, keine Worker, keine Ausführungslogik.
    """
    resolved_tools = tools or get_tool_paths()
    mi = media_info if media_info is not None else analyze_media(file_path, resolved_tools)
    ov = normalize_override_dict(file_override)

    pipeline_ctx = resolve_pipeline_context(
        mi,
        codec=codec,
        file_override=ov,
        global_preserve_dv=bool(global_preserve_dv),
        global_preserve_hdrplus=bool(global_preserve_hdrplus),
    )
    pipeline = str(_value(pipeline_ctx["pipeline"]))
    container = str(_value(pipeline_ctx["container"]))

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
        "overrides": ov,
        "move": {
            "planned_target": planned_target_dir(planned_target),
            "available": bool(planned_target_dir(planned_target)),
            "status": "planned" if planned_target_dir(planned_target) else "not_present",
        },
    }
