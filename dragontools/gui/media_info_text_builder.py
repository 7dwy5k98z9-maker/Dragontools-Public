# -*- coding: utf-8 -*-
"""Textaufbereitung für den Medieninfo-Dialog ohne Qt-Abhängigkeit."""
from __future__ import annotations

from typing import Any



def _build_rules_preview(*args, **kwargs):
    # Lazy import: reine Textformatierung bleibt ohne PyQt6 importier-/testbar.
    from ..core.rules_preview import build_rules_preview

    return build_rules_preview(*args, **kwargs)

def _yes_no(value: bool) -> str:
    return "Ja" if value else "Nein"


def _safe(value: Any, fallback: str = "—") -> str:
    if value is None:
        return fallback
    if isinstance(value, str) and not value.strip():
        return fallback
    return str(value)


def _channels_to_label(channels: Any) -> str:
    try:
        ch = int(channels)
    except Exception:
        return _safe(channels)
    if ch >= 8:
        return "7.1"
    if ch >= 6:
        return "5.1"
    if ch == 2:
        return "Stereo"
    if ch == 1:
        return "Mono"
    return str(ch)


def _bitrate_label(value: Any) -> str:
    if isinstance(value, (int, float)) and value > 0:
        return f"{int(value / 1000)} kbps"
    return "—"


def _duration_label(value: Any) -> str:
    try:
        seconds = float(value)
    except Exception:
        return "—"
    if seconds <= 0:
        return "—"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    rest = seconds - hours * 3600 - minutes * 60
    if hours:
        return f"{hours:02d}:{minutes:02d}:{rest:04.1f} ({seconds:.1f}s)"
    return f"{minutes:02d}:{rest:04.1f} ({seconds:.1f}s)"


def _int_label(value: Any) -> str:
    try:
        return f"{int(value):,}".replace(",", ".")
    except Exception:
        return "—"


def _fps_label(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "—"
    try:
        if "/" in raw:
            num_s, den_s = raw.split("/", 1)
            num = int(num_s)
            den = int(den_s)
            if den > 0:
                return f"{num}/{den} ({num / den:.3f} fps)"
    except Exception:
        pass
    return raw


def _lang_label(lang: Any) -> str:
    value = (str(lang).lower().strip() if lang is not None else "")
    mapping = {
        "de": "Deutsch",
        "deu": "Deutsch",
        "ger": "Deutsch",
        "en": "English",
        "eng": "English",
        "ja": "Japanese",
        "jpn": "Japanese",
        "fr": "Français",
        "es": "Español",
        "it": "Italiano",
        "und": "Unbekannt",
    }
    return mapping.get(value, value or "Unbekannt")


def _dolby_vision_label(mi: Any) -> str:
    if not bool(getattr(mi, "has_dv", False)):
        return "Nein"
    profile = getattr(mi, "dolby_vision_profile", None)
    codec_tag = getattr(mi, "dv_codec_tag", None)
    if profile and codec_tag:
        return f"Ja (Profil {profile} / {codec_tag})"
    if profile:
        return f"Ja (Profil {profile})"
    return "Ja (Profil unbekannt)"


def _video_lines(mi: Any) -> list[str]:
    video = getattr(mi, "primary_video", None)
    width = getattr(video, "width", None) if video else None
    height = getattr(video, "height", None) if video else None
    resolution = f"{width}×{height}" if width and height else "—"
    bit_depth = getattr(video, "bit_depth", None) if video else None
    bit_depth_text = f"{bit_depth} Bit" if bit_depth is not None else "—"
    color_range_raw = getattr(mi, "color_range", None)
    color_range_label = (
        "Full"
        if str(color_range_raw or "").strip().lower() in ("full", "pc", "full range")
        else ("Limited" if color_range_raw else "—")
    )
    return [
        "========= Video =========",
        f"Auflösung:      {resolution}",
        f"Codec:          {_safe(getattr(video, 'codec', None) if video else None)}",
        f"PixFmt:         {_safe(getattr(video, 'pix_fmt', None) if video else None)}",
        f"Videodauer:     {_duration_label(getattr(video, 'duration_s', None) if video else None)}",
        f"Frames:         {_int_label(getattr(video, 'frame_count', None) if video else None)}",
        f"Framerate:      {_fps_label(getattr(video, 'frame_rate', None) if video else None)}",
        f"Framerate-Modus: {_safe(getattr(video, 'frame_rate_mode', None) if video else None)}",
        f"HDR:            {'Ja' if bool(getattr(mi, 'is_hdr', False)) else 'Nein / SDR'}",
        f"HDR10+:         {_yes_no(bool(getattr(mi, 'has_hdr10plus', False)))}",
        f"Dolby Vision:   {_dolby_vision_label(mi)}",
        f"Bit-Tiefe:      {bit_depth_text}",
        "Farbraum:       "
        f"{_safe(getattr(video, 'color_space', None) if video else None)} / "
        f"{_safe(getattr(video, 'color_transfer', None) if video else None)} / "
        f"{_safe(getattr(video, 'color_primaries', None) if video else None)}",
        f"Farbbereich:    {color_range_label}",
    ]


def _audio_lines(mi: Any) -> list[str]:
    streams = list(getattr(mi, "audio_streams", []) or [])
    lines = ["========= Audio =========", f"Erkannte Audiostreams: {len(streams)}"]
    if not streams:
        lines.append("Keine Audiostreams gefunden.")
        return lines
    for idx, stream in enumerate(streams, start=1):
        line = (
            f"Audio {idx}: {_lang_label(getattr(stream, 'language', None))} | "
            f"{_safe(getattr(stream, 'codec', None))} | "
            f"{_channels_to_label(getattr(stream, 'channels', None))} | "
            f"{_bitrate_label(getattr(stream, 'bitrate', None))}"
        )
        title = _safe(getattr(stream, "title", None), "")
        if title:
            line += f" | Titel: {title}"
        lines.append(line)
    return lines


def _subtitle_lines(mi: Any) -> list[str]:
    streams = list(getattr(mi, "subtitle_streams", []) or [])
    forced_count = sum(1 for stream in streams if getattr(stream, "forced", False))
    lines = [
        "========= Untertitel =========",
        f"Gefunden: {len(streams)} (Forced: {forced_count}, Nicht-Forced: {len(streams) - forced_count})",
    ]
    if not streams:
        lines.append("Keine Untertitel gefunden.")
        return lines
    for idx, stream in enumerate(streams, start=1):
        line = (
            f"Untertitel {idx}: {_lang_label(getattr(stream, 'language', None))} | "
            f"{_safe(getattr(stream, 'codec', None))} | "
            f"Forced: {'Ja' if getattr(stream, 'forced', False) else 'Nein'}"
        )
        title = _safe(getattr(stream, "title", None), "")
        if title:
            line += f" | Titel: {title}"
        lines.append(line)
    return lines


def _audio_preview_lines(preview: dict[str, Any]) -> list[str]:
    audio = preview.get("audio", {}) or {}
    lines = ["Audio-Preview:", f"Override:       {_safe(audio.get('override_action'))}"]
    selected_streams = list(audio.get("selected_streams", []) or [])
    if not selected_streams:
        lines.append("Keine Audio-Preview verfügbar.")
        return lines
    for idx, entry in enumerate(selected_streams, start=1):
        lines.append(
            f"Audio {idx}: Stream {entry.get('index')} | "
            f"{_lang_label(entry.get('language'))} | "
            f"{_safe(entry.get('source_codec'))} → {_safe(entry.get('target_codec'))} | "
            f"{_channels_to_label(entry.get('source_channels'))} → {_channels_to_label(entry.get('target_channels'))} | "
            f"{_safe(entry.get('decision'))} | "
            f"{_bitrate_label(entry.get('target_bitrate'))}"
        )
    return lines


def _subtitle_preview_lines(preview: dict[str, Any]) -> list[str]:
    subtitles = preview.get("subtitles", {}) or {}
    lines = ["Untertitel-Preview:", f"Override:       {_safe(subtitles.get('override_mode'))}"]
    burn_candidate = subtitles.get("burn_candidate")
    if burn_candidate:
        lines.append(
            "Burn-In:        Ja | "
            f"Stream {burn_candidate.get('index')} | "
            f"{_lang_label(burn_candidate.get('language'))} | "
            f"{_safe(burn_candidate.get('codec'))} | "
            f"Forced: {_yes_no(bool(burn_candidate.get('forced')))}"
        )
    else:
        lines.append("Burn-In:        Nein")
        blocked_reason = subtitles.get("burn_blocked_reason")
        ambiguous = list(subtitles.get("ambiguous_burn_candidates", []) or [])
        if blocked_reason == "ambiguous" and ambiguous:
            lines.append(f"Auto-Burn:      Mehrdeutig ({len(ambiguous)} Kandidaten) - kein Auto-Burn gewählt")
        elif blocked_reason == "no_german_audio":
            lines.append("Auto-Burn:      Blockiert - keine deutsche Audiospur vorhanden")
        elif blocked_reason == "forced_full_sub_suspected":
            lines.append("Auto-Burn:      Blockiert - Forced-Spur wirkt wie Full Sub")
    for warning in list(subtitles.get("burn_warnings") or []):
        lines.append(f"Warnung:        {warning}")
    native_sidecars = list(subtitles.get("native_sidecar_candidates", []) or [])
    if native_sidecars:
        reason = (
            "MP4-Regel"
            if bool(subtitles.get("mp4_sidecars_enabled")) and not bool(subtitles.get("additional_sidecars_enabled"))
            else "zusätzlich"
        )
        lines.append(f"Sidecars:       {len(native_sidecars)} geplant ({reason})")
        for idx, entry in enumerate(native_sidecars, start=1):
            lines.append(
                f"Sidecar {idx}:  Stream {entry.get('index')} | "
                f"{_lang_label(entry.get('language'))} | "
                f"{_safe(entry.get('codec'))} | "
                f"Forced: {_yes_no(bool(entry.get('forced')))}"
            )
    elif bool(subtitles.get("additional_sidecars_enabled")):
        lines.append("Sidecars:       Aktiv, aber kein ausgewählter Untertitel passt")
    text_srt_candidates = list(subtitles.get("text_to_srt_candidates", []) or [])
    if text_srt_candidates:
        lines.append(f"Text→SRT:       {len(text_srt_candidates)} geplant")
        for idx, entry in enumerate(text_srt_candidates, start=1):
            lines.append(
                f"SRT {idx}:      Stream {entry.get('index')} | "
                f"{_lang_label(entry.get('language'))} | "
                f"{_safe(entry.get('codec'))} | "
                f"Forced: {_yes_no(bool(entry.get('forced')))}"
            )
    elif bool(subtitles.get("text_to_srt_sidecar_enabled")):
        lines.append("Text→SRT:       Aktiv, aber kein ausgewählter Text-Untertitel passt")

    if not bool(subtitles.get("container_copy_supported", True)):
        lines.append("Stream-Kopie:   Nicht im DV-Zielcontainer vorgesehen")
        if bool(subtitles.get("external_export_enabled")):
            export_candidates = list(subtitles.get("external_export_candidates", []) or [])
            if not export_candidates:
                lines.append("Extern:         Keine kompatiblen Untertitel")
            else:
                lines.append(f"Extern:         {len(export_candidates)} kompatible(r) Kandidat(en)")
                for idx, entry in enumerate(export_candidates, start=1):
                    lines.append(
                        f"Sub {idx}: Stream {entry.get('index')} | "
                        f"{_lang_label(entry.get('language'))} | "
                        f"{_safe(entry.get('codec'))} | "
                        f"Forced: {_yes_no(bool(entry.get('forced')))}"
                    )
        else:
            lines.append("Extern:         Nur bei aktivierter DV-Sub-Extraktion")
    else:
        copy_candidates = list(subtitles.get("stream_copy_candidates", []) or [])
        if not copy_candidates:
            lines.append("Stream-Kopie:   Keine kompatiblen Untertitel")
        else:
            lines.append(f"Stream-Kopie:   {len(copy_candidates)} kompatible(r) Kandidat(en)")
            for idx, entry in enumerate(copy_candidates, start=1):
                lines.append(
                    f"Sub {idx}: Stream {entry.get('index')} | "
                    f"{_lang_label(entry.get('language'))} | "
                    f"{_safe(entry.get('codec'))} | "
                    f"Forced: {_yes_no(bool(entry.get('forced')))}"
                )
    return lines


def _override_and_move_lines(preview: dict[str, Any]) -> list[str]:
    overrides = preview.get("overrides", {}) or {}
    legacy = overrides.get("_legacy", {}) if isinstance(overrides, dict) else {}
    processing_mode = "Strip-Only" if overrides.get("processing_mode") == "strip_only" else "Auto"
    lines = [
        "Overrides:",
        f"Verarbeitung:   {processing_mode}",
        f"Audio-Aktion:   {_safe(legacy.get('audio_action'))}",
        f"Burn-Modus:     {_safe(legacy.get('burn_mode'))}",
        f"Burn-Stream:    {_safe(legacy.get('burn_stream_index'))}",
        f"IMAX-Override:  {_yes_no(bool(overrides.get('imax')))}",
        "",
        "Move-Vorschlag:",
    ]
    move = preview.get("move", {}) or {}
    if move.get("available"):
        lines.append(f"Zielordner:     {_safe(move.get('planned_target'))}")
    else:
        lines.append("Zielordner:     Nicht vorhanden")
    return lines


def _rules_preview_lines(preview: dict[str, Any]) -> list[str]:
    lines = [
        f"Pipeline:       {_safe(preview.get('pipeline'))}",
        f"Zielcontainer:  {_safe(preview.get('target_container'))}",
        f"DV erhalten:    {_yes_no(bool(preview.get('dv_preserved')))}",
        f"HDR10+ erhalten: {_yes_no(bool(preview.get('hdr10plus_preserved')))}",
        "",
    ]
    lines.extend(_audio_preview_lines(preview))
    lines.append("")
    lines.extend(_subtitle_preview_lines(preview))
    lines.append("")
    lines.extend(_override_and_move_lines(preview))
    return lines


def build_media_info_text(
    file_path: str,
    *,
    mi: Any,
    file_override: dict[str, Any],
    planned_target: str | None,
    subtitle_rules: dict[str, Any],
    codec: str,
    global_preserve_dv: bool = True,
    global_preserve_hdrplus: bool = True,
) -> str:
    """Erzeugt den vollständigen DragonTools-Medieninfo-/Rules-Preview-Text."""
    lines: list[str] = [
        f"Genutzte Analysetools:        {getattr(mi, 'analysis_source', 'Unbekannt')}",
        "",
        *_video_lines(mi),
        "",
        *_audio_lines(mi),
        "",
        *_subtitle_lines(mi),
        "",
        "========= Rules Preview =========",
    ]
    try:
        preview = _build_rules_preview(
            file_path,
            codec=codec,
            file_override=file_override,
            planned_target=planned_target,
            subtitle_rules=subtitle_rules,
            media_info=mi,
            global_preserve_dv=global_preserve_dv,
            global_preserve_hdrplus=global_preserve_hdrplus,
        )
    except Exception as exc:
        lines.extend(["Rules Preview konnte nicht erstellt werden.", f"Fehler: {exc}"])
        return "\n".join(lines)

    lines.extend(_rules_preview_lines(preview))
    return "\n".join(lines)
