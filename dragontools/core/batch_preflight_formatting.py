from __future__ import annotations

from pathlib import Path
from typing import Any

def _text(value: Any, fallback: str = "-") -> str:
    if value is None:
        return fallback
    result = str(value).strip()
    return result or fallback


def _value(value: Any) -> Any:
    return getattr(value, "value", value)


def _channel_label(channels: Any) -> str:
    try:
        count = int(channels)
    except (TypeError, ValueError):
        return "?"
    if count <= 0:
        return "?"
    if count == 1:
        return "mono"
    if count == 2:
        return "stereo"
    if count == 6:
        return "5.1"
    if count == 8:
        return "7.1"
    return f"{count}ch"


def _video_summary(preview: dict[str, Any]) -> str:
    video = dict(preview.get("video") or {})
    source_codec = _text(preview.get("source_codec") or video.get("codec"), "?").upper()
    width = video.get("width")
    height = video.get("height")
    resolution = f"{width}x{height}" if width and height else "Auflösung unbekannt"
    bit_depth = video.get("bit_depth")
    bit_label = f"{bit_depth} bit" if bit_depth else ""
    parts = [source_codec, resolution]
    if bit_label:
        parts.append(bit_label)
    return " | ".join(parts)




def _target_resolution_summary(preview: dict[str, Any]) -> str:
    target = dict(preview.get("target_video") or {})
    resolution = _text(target.get("resolution"), "unbekannt")
    if target.get("autocrop_pending"):
        return f"{resolution} (vor Auto-Crop)"
    return resolution

def _hdr_summary(preview: dict[str, Any]) -> str:
    video = dict(preview.get("video") or {})
    parts: list[str] = []
    if video.get("has_dv"):
        profile = video.get("dv_profile")
        label = f"DV P{profile}" if profile else "DV"
        parts.append(f"{label} erhalten" if preview.get("dv_preserved") else f"{label} erkannt")
    if video.get("has_hdr10plus"):
        parts.append("HDR10+ erhalten" if preview.get("hdr10plus_preserved") else "HDR10+ erkannt")
    if not parts and video.get("is_hdr"):
        parts.append("HDR")
    if not parts:
        parts.append("SDR")
    ignored = set(str(v).lower() for v in preview.get("ignored_hdr") or [])
    if "dv" in ignored:
        parts.append("DV ignoriert")
    if "hdr10plus" in ignored:
        parts.append("HDR10+ ignoriert")
    return " | ".join(parts)


def _audio_stream_summary(entry: dict[str, Any]) -> str:
    index = _text(entry.get("index"), "?")
    lang = _text(entry.get("language"), "und")
    source = _text(entry.get("source_codec"), "?")
    source_channels = _channel_label(entry.get("source_channels"))
    if entry.get("decision") == "copy":
        target = "copy"
    else:
        target = f"{_text(entry.get('target_codec'), '?')} {_channel_label(entry.get('target_channels'))}"
        bitrate = entry.get("target_bitrate")
        if bitrate:
            target = f"{target} {bitrate}k"
    suffix = " (Stereo-Zusatz)" if entry.get("is_extra_stereo") else ""
    return f"#{index} {lang} {source} {source_channels} -> {target}{suffix}"


def _bitrate_label(value: Any) -> str:
    try:
        bitrate = int(value)
    except (TypeError, ValueError):
        return ""
    if bitrate <= 0:
        return ""
    if bitrate > 10000:
        bitrate = int(round(bitrate / 1000))
    return f"{bitrate} kbps"


def _stream_list_label(streams: list[dict[str, Any]], *, limit: int = 6) -> str:
    labels: list[str] = []
    for entry in streams[:limit]:
        flags = []
        if entry.get("forced"):
            flags.append("forced")
        codec = _text(entry.get("codec"), "?")
        lang = _text(entry.get("language"), "und")
        suffix = f" ({', '.join(flags)})" if flags else ""
        labels.append(f"#{_text(entry.get('index'), '?')} {lang}/{codec}{suffix}")
    remaining = len(streams) - len(labels)
    if remaining > 0:
        labels.append(f"+{remaining} weitere")
    return ", ".join(labels) if labels else "-"


def _audio_summary(preview: dict[str, Any]) -> str:
    audio = dict(preview.get("audio") or {})
    streams = list(audio.get("selected_streams") or [])
    if not streams:
        source_count = int(audio.get("source_count") or 0)
        return "Keine Auswahl" if source_count else "Keine Audioquelle"
    labels = [_audio_stream_summary(dict(entry)) for entry in streams[:3]]
    remaining = len(streams) - len(labels)
    if remaining > 0:
        labels.append(f"+{remaining} weitere")
    return "; ".join(labels)


def _subtitle_summary(preview: dict[str, Any]) -> str:
    subs = dict(preview.get("subtitles") or {})
    source_count = int(subs.get("source_count") or 0)
    if not source_count:
        return "Keine Untertitelquelle"

    parts: list[str] = []
    burn = subs.get("burn_candidate") if subs.get("burn_in") else None
    if burn:
        burn = dict(burn)
        parts.append(f"Burn #{_text(burn.get('index'), '?')} {_text(burn.get('language'), 'und')}")

    if not subs.get("container_copy_supported", True):
        count = int(subs.get("external_export_candidate_count") or 0)
        parts.append(f"Extern {count}" if count else "Extern 0")
    else:
        count = int(subs.get("copy_candidate_count") or 0)
        parts.append(f"Copy {count}" if count else "Copy 0")

    native_sidecars = int(subs.get("native_sidecar_candidate_count") or 0)
    text_srt_sidecars = int(subs.get("text_to_srt_candidate_count") or 0)
    if native_sidecars:
        parts.append(f"Sidecar {native_sidecars}")
    if text_srt_sidecars:
        parts.append(f"Text->SRT {text_srt_sidecars}")

    return " | ".join(parts) if parts else "Keine Auswahl"


def _target_summary(preview: dict[str, Any], fs_info: dict[str, Any] | None = None) -> str:
    container = _text(preview.get("target_container"), "?")
    fs_info = fs_info or {}
    output_path = _text(fs_info.get("final_output_path") or fs_info.get("output_path"), "")
    target = Path(output_path).name if output_path else f".{container}"
    move = dict(preview.get("move") or {})
    planned = _text(move.get("planned_target"), "")
    if planned:
        return f"{target} | Ziel: {planned}"
    return target


def _pipeline_summary(preview: dict[str, Any]) -> str:
    pipeline = str(_value(preview.get("pipeline") or "standard"))
    container = _text(preview.get("target_container"), "?")
    summary = f"{pipeline} -> .{container}"
    overrides = dict(preview.get("overrides") or {})
    if overrides.get("processing_mode") == "strip_only":
        summary = f"{summary} | Strip-Only"
    manual = overrides.get("encoder_override")
    if isinstance(manual, dict):
        encoder = _text(manual.get("encoder"), "?").upper()
        quality = manual.get("quality", manual.get("crf"))
        scale = _text(manual.get("scale_mode") or manual.get("scale"), "original")
        q_label = {"NVENC": "CQ", "QSV": "Q", "AMF": "QP"}.get(encoder, "CRF")
        quality_text = f" {q_label} {quality}" if quality is not None else ""
        summary = f"{summary} | Encoder: {encoder}{quality_text} | {scale}"
    else:
        profile = overrides.get("encoder_profile")
        if isinstance(profile, dict):
            label = _text(profile.get("label") or profile.get("key"), "")
            if label:
                summary = f"{summary} | Profil: {label}"
    return summary


def _profile_summary(preview: dict[str, Any]) -> str:
    overrides = dict(preview.get("overrides") or {})
    manual = overrides.get("encoder_override")
    if isinstance(manual, dict):
        encoder = _text(manual.get("encoder"), "?").upper()
        return f"Manueller Encoder ({encoder})"
    profile = overrides.get("encoder_profile")
    if isinstance(profile, dict):
        label = _text(profile.get("label") or profile.get("key"), "")
        if label:
            return label
    if overrides:
        return "Datei-Override"
    return "Standard"
