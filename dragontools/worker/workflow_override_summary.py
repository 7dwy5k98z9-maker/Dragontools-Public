# -*- coding: utf-8 -*-
from __future__ import annotations


def _tristate(value) -> str:
    return "global" if value is None else ("an" if bool(value) else "aus")


def _mode(value) -> str:
    return {"on": "an", "off": "aus", "inherit": "global"}.get(
        str(value or "inherit").lower(), str(value or "global")
    )


def format_override_summary(override: dict, profile_label: str = "") -> str:
    parts: list[str] = []
    if profile_label:
        label = "Encoder-Override" if override.get("encoder_override") else "Encoderprofil"
        parts.append(f"{label}: {profile_label}")
    if override.get("processing_mode") == "strip_only":
        parts.append("Verarbeitung: Strip-Only")
    if override.get("imax"):
        parts.append("IMAX: manuell erhalten")
    for key, label in (("preserve_dv", "Dolby Vision erhalten"), ("preserve_hdrplus", "HDR10+ erhalten"),
                       ("sdr_hdr", "SDR→HDR"), ("generate_hdr10plus", "HDR10+ erzeugen")):
        if override.get(key) is not None:
            parts.append(f"{label}: {_tristate(override.get(key))}")
    audio_tracks = list(override.get("audio_tracks") or [])
    if override.get("audio_mode") == "custom" or audio_tracks:
        parts.append(f"Audio: manuell ({len(audio_tracks)} Spur-Regel(n))")
    subtitle_tracks = list(override.get("subtitle_tracks") or [])
    if override.get("subtitle_mode") == "custom" or subtitle_tracks:
        keep_count = sum(1 for item in subtitle_tracks if item.get("keep"))
        burn_count = sum(1 for item in subtitle_tracks if item.get("burn_in"))
        parts.append(f"Untertitel: manuell ({keep_count} behalten, {burn_count} Burn-In)")
    drc = override.get("audio_drc")
    if isinstance(drc, dict):
        parts.append(f"DRC/Nachtmodus: {_mode(drc.get('mode'))} ({drc.get('scale', 1.0)})")
    loudnorm = override.get("audio_loudnorm")
    if isinstance(loudnorm, dict):
        parts.append(f"Lautheitsnormalisierung: {_mode(loudnorm.get('mode'))} ({loudnorm.get('i', -18.0)} LUFS)")
    return " | ".join(parts)


__all__ = ["format_override_summary"]
