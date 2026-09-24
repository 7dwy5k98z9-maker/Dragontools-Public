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
from ..core.file_override_normalization import normalize_override_dict


def configure_optional_runtime_features(worker, tools) -> None:
    """Ermittelt optionale SDR→HDR- und HDR10+-Generator-Capabilities."""
    options = worker._job_state.encoder_options

    libplacebo_available = ffmpeg_has_libplacebo(str(tools.ffmpeg))
    options["_sdr_hdr_libplacebo_available"] = bool(libplacebo_available)

    resolve_available = generator_executable_available(tools.davinci_resolve)
    options["_davinci_resolve_available"] = bool(resolve_available)

    _configure_hdr10plus_generator(worker, tools, options)

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
        configure_comfyui_runtime(worker, tools, options)
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
    generator_path = str(tools.hdr10plus_generator)
    generator_available = generator_executable_available(generator_path)
    generator_version = ""

    if generator_enabled and generator_available:
        probe = HDR10PlusGeneratorClient(generator_path, worker=worker, log=worker.log).probe_version()
        generator_available = bool(probe.success and probe.version)
        generator_version = probe.version if generator_available else ""
        if not generator_available:
            worker.log(
                "⚠️ Dragon HDR10+ Generator gefunden, aber --version liefert keinen gültigen JSON-Vertrag: "
                f"{probe.error or probe.message or 'unbekannter Fehler'}",
                "warn",
            )

    options["_hdr10plus_generator_available"] = bool(generator_enabled and generator_available)
    options["_hdr10plus_generator_version"] = generator_version

    if generator_enabled:
        if generator_available:
            worker.log(f"🧪 Dragon HDR10+ Generator bereit (Version {generator_version}).", "info")
        else:
            worker.log(
                "⚠️ Dragon HDR10+ Generator aktiviert, aber nicht verfügbar; bestehende HDR/DV-Pfade bleiben unverändert.",
                "warn",
            )



__all__ = ["configure_optional_runtime_features"]
