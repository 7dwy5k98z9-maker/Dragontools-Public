from __future__ import annotations

from typing import Any

from ..rules.subtitle_rules import (
    additional_sidecars_enabled,
    build_mp4_subtitle_storage_plan,
    compute_subtitle_plan,
    mp4_sidecars_enabled,
    text_to_srt_sidecar_enabled,
)
from .rules_preview_common import lang

TEXT_TO_SRT_PREVIEW_CODECS = {
    "ass", "ssa", "subrip", "srt", "subt", "mov_text", "tx3g", "text", "webvtt",
}


def subtitle_entry(stream) -> dict[str, Any]:
    return {
        "index": stream.index,
        "language": lang(stream.language),
        "forced": bool(stream.forced),
        "codec": (stream.codec or "").lower(),
        "title": stream.title,
    }


def subtitle_entries(streams) -> list[dict[str, Any]]:
    return [subtitle_entry(stream) for stream in streams]


def native_srt_sidecar_indices(streams) -> set[int]:
    return {
        int(stream.index)
        for stream in streams
        if str(getattr(stream, "codec", "") or "").lower()
        in {"subrip", "srt", "subt", "mov_text", "tx3g", "text"}
    }


def build_subtitle_preview(
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
            selected_for_sidecars if (mp4_export_enabled or additional_enabled)
            else list(storage.external_streams)
        )
    elif not copy_supported:
        stream_copy_candidates = []
        normal_sidecar_streams = selected_for_sidecars if (mp4_export_enabled or additional_enabled) else []
    else:
        stream_copy_candidates = keep
        normal_sidecar_streams = selected_for_sidecars if additional_enabled else []

    normal_srt_indices = native_srt_sidecar_indices(normal_sidecar_streams)
    text_srt_candidates = [
        s for s in selected_for_sidecars
        if str(getattr(s, "codec", "") or "").lower() in TEXT_TO_SRT_PREVIEW_CODECS
        and int(s.index) not in normal_srt_indices
    ]
    sidecar_fields = {
        "mp4_sidecars_enabled": mp4_export_enabled,
        "additional_sidecars_enabled": additional_enabled,
        "text_to_srt_sidecar_enabled": text_srt_enabled,
        "native_sidecar_candidates": subtitle_entries(normal_sidecar_streams),
        "native_sidecar_candidate_count": len(normal_sidecar_streams),
        "text_to_srt_candidates": [subtitle_entry(s) for s in text_srt_candidates] if text_srt_enabled else [],
        "text_to_srt_candidate_count": len(text_srt_candidates) if text_srt_enabled else 0,
        "sidecar_export_enabled": bool(normal_sidecar_streams or (text_srt_enabled and text_srt_candidates)),
    }

    common = _burn_fields(mi, plan, burn_sub)
    if pipeline in {"dv", "av1_dv"}:
        return {
            **common,
            "container_copy_supported": False,
            "stream_copy_candidates": [],
            "copy_candidate_count": 0,
            "external_export_enabled": bool(sidecar_fields["sidecar_export_enabled"]),
            "external_export_candidates": subtitle_entries(normal_sidecar_streams),
            "external_export_candidate_count": len(normal_sidecar_streams),
            **sidecar_fields,
        }

    return {
        **common,
        "container_copy_supported": True,
        "stream_copy_candidates": subtitle_entries(stream_copy_candidates),
        "copy_candidate_count": len(stream_copy_candidates),
        **sidecar_fields,
    }


def _burn_fields(mi, plan, burn_sub) -> dict[str, Any]:
    return {
        "override_mode": plan.override_mode,
        "source_count": len(mi.subtitle_streams),
        "burn_in": burn_sub is not None,
        "burn_candidate": subtitle_entry(burn_sub) if burn_sub is not None else None,
        "burn_blocked_reason": plan.burn_blocked_reason,
        "burn_warnings": list(getattr(plan, "burn_warnings", ()) or ()),
        "burn_event_rate": getattr(plan, "burn_event_rate", None),
        "ambiguous_burn_candidates": [subtitle_entry(stream) for stream in plan.burn_candidates],
    }
