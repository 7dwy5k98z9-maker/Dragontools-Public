# -*- coding: utf-8 -*-
from __future__ import annotations

from ..core.type_utils import _safe_bool, _safe_float, _safe_int

_LANG_MAP = {
    "de": "Deutsch", "deu": "Deutsch", "ger": "Deutsch",
    "en": "English", "eng": "English",
    "ja": "Japanese", "jpn": "Japanese",
    "fr": "Français", "es": "Español", "it": "Italiano",
    "und": "Unbekannt",
}

def _lang_label(value) -> str:
    val = (str(value).lower().strip() if value is not None else "")
    return _LANG_MAP.get(val, val or "Unbekannt")


def _audio_meta_text(stream) -> str:
    bitrate = getattr(stream, "bitrate", None)
    if isinstance(bitrate, (int, float)) and bitrate:
        bitrate_text = f"{int(bitrate/1000)} kbps"
    else:
        bitrate_text = "—"
    channels = getattr(stream, "channels", None)
    return (
        f"{_lang_label(getattr(stream, 'language', None))} | "
        f"{getattr(stream, 'codec', '—')} | "
        f"{channels or '—'} ch | "
        f"{bitrate_text}"
    )


def _load_override_state(ov: dict) -> dict:
    """Baut aus dem persistierten Override-Dict den Initialzustand für den Dialog."""
    old_audio_action = ov.get("audio_action", "auto")
    audio_mode_value = ov.get("audio_mode")
    if audio_mode_value not in {"auto", "custom"}:
        audio_mode_value = "custom" if old_audio_action != "auto" else "auto"

    audio_track_map = {}
    raw_audio_tracks = ov.get("audio_tracks")
    if isinstance(raw_audio_tracks, list):
        for entry in raw_audio_tracks:
            if not isinstance(entry, dict):
                continue
            index = _safe_int(entry.get("index"), None)
            if index is not None:
                audio_track_map[index] = dict(entry)

    old_burn_mode = ov.get("burn_mode", "auto")
    old_burn_stream_index = ov.get("burn_stream_index")
    subtitle_mode_value = ov.get("subtitle_mode")
    if subtitle_mode_value not in {"auto", "custom"}:
        subtitle_mode_value = "custom" if old_burn_mode != "auto" else "auto"

    processing_mode_value = str(ov.get("processing_mode", "auto") or "auto").lower()
    if processing_mode_value not in {"auto", "strip_only"}:
        processing_mode_value = "strip_only" if _safe_bool(ov.get("strip_only"), False) else "auto"

    def _audio_processing_state(key: str, value_key: str, default: float) -> dict:
        raw = ov.get(key)
        if not isinstance(raw, dict):
            return {"mode": "inherit", value_key: default}
        mode = str(raw.get("mode", "inherit") or "inherit").lower()
        if mode not in {"inherit", "on", "off"}:
            mode = "inherit"
        value = _safe_float(raw.get(value_key), default)
        return {"mode": mode, value_key: value}

    subtitle_track_map = {}
    raw_subtitle_tracks = ov.get("subtitle_tracks")
    if isinstance(raw_subtitle_tracks, list):
        for entry in raw_subtitle_tracks:
            if not isinstance(entry, dict):
                continue
            index = _safe_int(entry.get("index"), None)
            if index is not None:
                subtitle_track_map[index] = dict(entry)

    return {
        "old_audio_action": old_audio_action,
        "audio_mode_value": audio_mode_value,
        "audio_track_map": audio_track_map,
        "old_burn_mode": old_burn_mode,
        "old_burn_stream_index": old_burn_stream_index,
        "subtitle_mode_value": subtitle_mode_value,
        "subtitle_track_map": subtitle_track_map,
        "processing_mode_value": processing_mode_value,
        "audio_drc": _audio_processing_state("audio_drc", "scale", 1.0),
        "audio_loudnorm": _audio_processing_state("audio_loudnorm", "i", -18.0),
    }
