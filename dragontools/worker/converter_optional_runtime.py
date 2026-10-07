# -*- coding: utf-8 -*-
"""Optionale Runtime-Capabilities des Standard-Converters.

Dieses Modul hält die Erkennung optionaler Backends bewusst aus dem zentralen
``ConverterRuntimeBuilder`` heraus. Fehlende Werkzeuge oder lokale Dienste dürfen
den bestehenden FFmpeg-/DV-/HDR10+-Betrieb niemals blockieren.
"""
from __future__ import annotations

from .hdr10plus_generator_client import HDR10PlusGeneratorClient, generator_executable_available
from .sdr_hdr_runtime import ffmpeg_has_libplacebo
from .comfyui_runtime import configure_comfyui_runtime
from .log_dispatch import dispatch_log
from ..core.file_override_normalization import normalize_override_dict
from ..core.encoder_profile_override import (
    file_override_may_enable_encoder_option, effective_encoder_settings,
    normalize_encoder_override, normalize_profile_override,
)


def configure_optional_runtime_features(worker, tools) -> None:
    """Ermittelt optionale SDR→HDR- und HDR10+-Generator-Capabilities."""
    options = worker._job_state.encoder_options

    libplacebo_available = ffmpeg_has_libplacebo(str(tools.ffmpeg))
    options["_sdr_hdr_libplacebo_available"] = bool(libplacebo_available)

    resolve_available = generator_executable_available(tools.davinci_resolve)
    options["_davinci_resolve_available"] = bool(resolve_available)

    _configure_hdr10plus_generator(worker, tools, options)
    for raw in dict(getattr(worker._job_state, "file_overrides", {}) or {}).values():
        configure_optional_file_runtime(worker, tools, raw, profiles_only=True)

    global_sdr_hdr = bool(options.get("sdr_hdr_enabled", False))
    per_file_sdr_hdr = any(
        normalize_override_dict(raw).get("sdr_hdr") is True
        for raw in dict(getattr(worker._job_state, "file_overrides", {}) or {}).values()
    )
    if not (global_sdr_hdr or per_file_sdr_hdr):
        return

    backend = str(options.get("sdr_hdr_backend", "ffmpeg") or "ffmpeg").strip().lower()
    if backend == "davinci_free":
        worker.log(
            "🧪 SDR→HDR Backend: DaVinci Resolve Free erkannt; automatische Render-Steuerung "
            "ist bewusst nur vorbereitet und bleibt deaktiviert."
            if resolve_available
            else "⚠️ SDR→HDR Backend: DaVinci Resolve Free gewählt, aber Resolve wurde nicht gefunden; "
            "bestehende FFmpeg-/Standardpfade bleiben unverändert.",
            "info" if resolve_available else "warn",
        )
        return

    if backend == "comfyui":
        _probe_comfyui_backend(worker, tools, options)
        return

    worker.log(
        "🧪 SDR→HDR Enhancement: FFmpeg/libplacebo verfügbar."
        if libplacebo_available
        else "⚠️ SDR→HDR Enhancement angefordert, aber FFmpeg/libplacebo fehlt; "
        "normaler SDR-Encode bleibt aktiv.",
        "info" if libplacebo_available else "warn",
    )


def _configure_hdr10plus_generator(worker, tools, options: dict) -> None:
    generator_enabled = bool(options.get("hdr10plus_generator_enabled", False))
    per_file_enabled = any(
        normalize_override_dict(raw).get("generate_hdr10plus") is True
        or file_override_may_enable_encoder_option(raw, "hdr10plus_generator_enabled")
        for raw in dict(getattr(worker._job_state, "file_overrides", {}) or {}).values()
    )
    generator_requested = bool(generator_enabled or per_file_enabled)
    generator_path = str(tools.hdr10plus_generator)
    generator_available = (
        generator_executable_available(generator_path) if generator_requested else False
    )
    generator_version = ""

    if generator_requested and generator_available:
        probe = HDR10PlusGeneratorClient(
            generator_path,
            worker=worker,
            log=worker.log,
            ffmpeg_path=getattr(tools, "ffmpeg", "ffmpeg"),
            ffprobe_path=getattr(tools, "ffprobe", "ffprobe"),
        ).probe_version()
        generator_available = bool(probe.success and probe.version)
        generator_version = probe.version if generator_available else ""
        if not generator_available:
            worker.log(
                "⚠️ Dragon HDR10+ Generator gefunden, aber --version liefert keinen gültigen JSON-Vertrag: "
                f"{probe.error or probe.message or 'unbekannter Fehler'}",
                "warn",
            )

    options["_hdr10plus_generator_available"] = bool(generator_requested and generator_available)
    options["_hdr10plus_generator_version"] = generator_version

    if generator_requested:
        request_source = (
            "globale/per-Datei-Einstellung"
            if generator_enabled and per_file_enabled
            else "per-Datei-Override"
            if per_file_enabled
            else "globale Einstellung"
        )
        if generator_available:
            worker.log(
                f"🧪 Dragon HDR10+ Generator bereit (Version {generator_version}, {request_source}).",
                "info",
            )
        else:
            worker.log(
                "⚠️ Dragon HDR10+ Generator angefordert, aber nicht verfügbar; bestehende HDR/DV-Pfade bleiben unverändert.",
                "warn",
            )



def configure_optional_file_runtime(worker, tools, override: dict, *, profiles_only: bool = False) -> None:
    """Probe the effective profile's backend and keep readiness on that profile."""
    job = worker._job_state
    codec = getattr(job, "codec", "h265")
    normalized = normalize_override_dict(override)
    if normalize_encoder_override(normalized.get("encoder_override"), default_codec=codec) is not None:
        carrier = override["encoder_override"]
    elif normalize_profile_override(normalized.get("encoder_profile"), default_codec=codec) is not None:
        carrier = override["encoder_profile"]
    else:
        carrier = None
    if carrier is None and profiles_only:
        return
    effective = effective_encoder_settings(default_codec=codec,
        default_crf=getattr(job, "crf", 23), default_preset=getattr(job, "preset", "medium"),
        default_scale_mode=getattr(job, "scale_mode", "original"),
        default_encoder_options=getattr(job, "encoder_options", {}), file_override=normalized)["encoder_options"]
    if not effective.get("sdr_hdr_enabled") or effective.get("sdr_hdr_backend") != "comfyui":
        return
    _probe_comfyui_backend(worker, tools, effective)
    capabilities = {key: value for key, value in effective.items() if key.startswith("_comfyui_")}
    if carrier is None:
        override["_encoder_runtime_capabilities"] = capabilities
    else:
        if not isinstance(carrier.get("encoder_options"), dict):
            carrier["encoder_options"] = {}
        carrier["encoder_options"].update(capabilities)


def _probe_comfyui_backend(worker, tools, options: dict) -> None:
    try:
        configure_comfyui_runtime(worker, tools, options)
    except Exception as exc:
        options["_comfyui_backend_ready"] = False
        options["_comfyui_api_available"] = False
        options["_comfyui_model_error"] = str(exc)
        dispatch_log(worker.log, f"⚠️ Optionale ComfyUI-Prüfung fehlgeschlagen: {exc}", "warn")


__all__ = ["configure_optional_runtime_features", "configure_optional_file_runtime"]
