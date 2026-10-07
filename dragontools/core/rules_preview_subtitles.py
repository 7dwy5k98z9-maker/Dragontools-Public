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
    from dataclasses import replace
    from ..rules.subtitle_output_plan import select_sidecar_streams
    from ..rules.subtitle_storage import mkv_internal_subtitle_streams, pgs_original_storage, pgs_to_srt_enabled
    from .models import normalize_override_dict

    strip_only = ov.get("processing_mode") == "strip_only"
    target_container = str(container or "mkv").lower()
    selection = select_sidecar_streams(
        mi.subtitle_streams, audio_streams=mi.audio_streams,
        media_duration_s=getattr(mi, "duration_s", None), file_override=ov,
        subtitle_rules=subtitle_rules or {}, preserve_burn_candidate=strip_only,
        normalize_override=normalize_override_dict, compute_plan=compute_subtitle_plan,
        build_storage_plan=build_mp4_subtitle_storage_plan,
        sidecars_enabled=mp4_sidecars_enabled,
        additional_sidecars_enabled=additional_sidecars_enabled,
        text_to_srt_sidecar_enabled=text_to_srt_sidecar_enabled,
        pgs_to_srt_enabled=pgs_to_srt_enabled, pgs_original_storage=pgs_original_storage,
        container=target_container,
    )
    plan = selection.plan
    if target_container in {"mp4", "m4v", "mov"}:
        internal = list(selection.storage.internal_streams)
    else:
        internal = ([plan.burn_sub] if strip_only and plan.burn_sub is not None else []) + list(plan.keep_streams)
        internal = mkv_internal_subtitle_streams(internal, subtitle_rules=subtitle_rules)
    common = _burn_fields(mi, replace(plan, burn_sub=None) if strip_only else plan,
        None if strip_only else plan.burn_sub)
    native = list(selection.normal_streams)
    text_srt = list(selection.ass_srt_streams)
    pgs_srt = list(selection.pgs_srt_streams)
    return {
        **common,
        "container_copy_supported": True,
        "stream_copy_candidates": subtitle_entries(internal),
        "copy_candidate_count": len(internal),
        "external_export_enabled": bool(native or text_srt or pgs_srt),
        "external_export_candidates": subtitle_entries(native),
        "external_export_candidate_count": len(native),
        "mp4_sidecars_enabled": target_container == "mp4" and mp4_sidecars_enabled(subtitle_rules),
        "additional_sidecars_enabled": additional_sidecars_enabled(subtitle_rules),
        "text_to_srt_sidecar_enabled": text_to_srt_sidecar_enabled(subtitle_rules),
        "pgs_to_srt_enabled": pgs_to_srt_enabled(subtitle_rules),
        "pgs_to_srt_candidates": subtitle_entries(pgs_srt),
        "pgs_to_srt_candidate_count": len(pgs_srt),
        "native_sidecar_candidates": subtitle_entries(native),
        "native_sidecar_candidate_count": len(native),
        "text_to_srt_candidates": subtitle_entries(text_srt),
        "text_to_srt_candidate_count": len(text_srt),
        "sidecar_export_enabled": bool(native or text_srt or pgs_srt),
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
