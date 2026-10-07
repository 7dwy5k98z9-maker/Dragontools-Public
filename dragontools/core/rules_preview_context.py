from __future__ import annotations

from .codec_utils import SUPPORTED_TARGET_CODECS, normalize_target_codec
from .sdr_hdr_enhancement import decide_sdr_hdr_enhancement
from .type_utils import _safe_bool
from ..rules.pipeline_selector import resolve_pipeline_context


def build_sdr_hdr_preview(mi, options: dict, codec: str, *, strip_only: bool) -> dict:
    sdr_hdr_requested = _safe_bool(options.get("sdr_hdr_enabled", False), False)
    sdr_hdr_backend = str(options.get("sdr_hdr_backend", "ffmpeg") or "ffmpeg").strip().lower()
    capability_keys = {
        "ffmpeg": {"_sdr_hdr_libplacebo_available"},
        "davinci_free": {"_davinci_resolve_available"},
        "comfyui": {
            "_comfyui_api_available",
            "_comfyui_model_assets_ready",
            "_comfyui_required_nodes_available",
            "_comfyui_workflow_valid",
        },
    }.get(sdr_hdr_backend, set())
    sdr_hdr_capability_known = bool(capability_keys) and capability_keys.issubset(options)
    sdr_hdr_applied = False
    sdr_hdr_reason = "deaktiviert"
    if sdr_hdr_requested:
        if sdr_hdr_capability_known:
            sdr_hdr_decision = decide_sdr_hdr_enhancement(
                mi,
                target_codec=codec,
                encoder_options=options,
            )
            sdr_hdr_applied = bool(sdr_hdr_decision.applied)
            sdr_hdr_reason = str(sdr_hdr_decision.reason or "")
        else:
            sdr_hdr_reason = (
                "SDR→HDR ist angefordert; die Backend-Verfügbarkeit wird erst beim Worker-Start geprüft."
            )
    if strip_only:
        sdr_hdr_applied = False
        sdr_hdr_reason = "Strip-Only führt keine SDR→HDR-Konvertierung aus."
    return {
        "sdr_hdr_requested": sdr_hdr_requested,
        "sdr_hdr_backend": sdr_hdr_backend,
        "sdr_hdr_capability_known": sdr_hdr_capability_known,
        "sdr_hdr_applied": sdr_hdr_applied,
        "sdr_hdr_reason": sdr_hdr_reason,
    }


def resolve_preview_pipeline(mi, ov, encoder_settings, *,
    global_preserve_dv, global_preserve_hdrplus, standard_container, dv_container,
    hdr10plus_generator_enabled, hdr10plus_generator_available):
    effective_options = dict(encoder_settings.get("encoder_options") or {})
    # Pipeline policy must use the same per-file profile/options as the actual
    # encoder worker.  Otherwise Preflight can display one HDR policy while
    # runtime selects another pipeline/container from the global options.
    effective_preserve_dv = _safe_bool(
        effective_options.get("preserve_dv", global_preserve_dv), bool(global_preserve_dv)
    )
    effective_preserve_hdrplus = _safe_bool(
        effective_options.get("preserve_hdrplus", global_preserve_hdrplus),
        bool(global_preserve_hdrplus),
    )
    effective_generator_enabled = _safe_bool(
        effective_options.get("hdr10plus_generator_enabled", hdr10plus_generator_enabled),
        bool(hdr10plus_generator_enabled),
    )
    effective_generator_available = _safe_bool(
        effective_options.get("_hdr10plus_generator_available", hdr10plus_generator_available),
        bool(hdr10plus_generator_available),
    )
    pipeline_codec = str(encoder_settings["codec"])
    if ov.get("processing_mode") == "strip_only":
        primary = getattr(mi, "primary_video", None)
        source_codec = normalize_target_codec(getattr(primary, "codec", ""), strict=False)
        if source_codec in SUPPORTED_TARGET_CODECS:
            pipeline_codec = source_codec

    pipeline_ctx = resolve_pipeline_context(
        mi,
        codec=pipeline_codec,
        file_override=ov,
        global_preserve_dv=effective_preserve_dv,
        global_preserve_hdrplus=effective_preserve_hdrplus,
        standard_container=str(standard_container),
        dv_container=str(dv_container),
        hdr10plus_generator_enabled=effective_generator_enabled,
        hdr10plus_generator_available=effective_generator_available,
    )
    if ov.get("processing_mode") == "strip_only":
        pipeline_ctx["generate_hdr10plus"] = False
        pipeline_ctx["hdr10plus_generation_code"] = "STRIP_ONLY"
        pipeline_ctx["hdr10plus_generation_reason"] = "Strip-Only übernimmt den vorhandenen Videostream unverändert."
    return pipeline_ctx
