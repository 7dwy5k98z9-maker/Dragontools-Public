# -*- coding: utf-8 -*-
"""Low-level audio-rule helpers and immutable defaults."""
from __future__ import annotations

from typing import Any

from ..core.config_migration import SCHEMA_VERSION_KEY
from ..core.type_utils import _safe_bool

def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, "", "N/A"):
            return default
        return int(value)
    except Exception:
        try:
            return int(float(value))
        except Exception:
            return default


def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, safe_int(value, default)))


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", "N/A"):
            return default
        return float(str(value).replace(",", "."))
    except Exception:
        return default


def _clamp_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    number = safe_float(value, default)
    return max(minimum, min(maximum, number))


def normalize_audio_codec(codec: str) -> str:
    c = (codec or "").lower()
    aliases = {
        "dts_hd_ma":   "dts-hd ma",
        "dts_hd_hra":  "dts-hd hra",
        "dts-hd":      "dts-hd ma",
        "truehd":      "truehd",
        "mlp":         "truehd",
        "dca":         "dts",
        "eac3":        "eac3",
        "ac3":         "ac3",
        "aac":         "aac",
        "flac":        "flac",
        "pcm_s16le":   "pcm",
        "pcm_s24le":   "pcm",
        "pcm_s32le":   "pcm",
        "pcm_bluray":  "pcm",
        "mp2":         "mp2",
        "mp3":         "mp3",
    }
    return aliases.get(c, c)


def max_channels_for_audio_codec(codec: str) -> int:
    """Maximale Ziel-Kanalzahl, die DragonTools für Encoding sicher plant."""
    codec_norm = normalize_audio_codec(codec)
    if codec_norm in {"ac3", "eac3"}:
        return 6
    if codec_norm in {"aac", "copy"}:
        return 8
    return 8


def clamp_audio_target_to_codec_cap(target: dict[str, Any], source_channels: int) -> dict[str, Any]:
    """Begrenzt Zielkanaele auf das, was der Zielcodec sauber encoden kann."""
    result = dict(target or {})
    codec_norm = normalize_audio_codec(str(result.get("codec") or ""))
    if codec_norm == "copy":
        return result
    requested_channels = safe_int(result.get("channels"), source_channels or 2)
    codec_cap = max_channels_for_audio_codec(codec_norm)
    result["channels"] = max(1, min(requested_channels, source_channels or requested_channels, codec_cap))
    return result


_DEFAULT_RULES: dict[str, Any] = {
    SCHEMA_VERSION_KEY: 4,
    "language_priority": ["de", "en"],
    "max_languages": 1,
    "tracks_per_language": 1,
    "fallback_if_no_priority_match": "keep_all",
    "ignore_commentary_tracks": True,
    "ignore_descriptive_audio": True,
    "preferred_languages": ["de", "deu", "ger"],
    "fallback_languages":  ["en", "eng"],
    "max_tracks":          1,
    "passthrough_codecs":  ["aac", "ac3", "eac3"],
    "extra_stereo":        False,  # Zusatz-Stereo-Downmix für Mehrkanal-Spuren
    "extra_stereo_codec":  "aac",  # Codec für Zusatz-Stereo-Downmix
    "extra_stereo_bitrate_k": 256, # Bitrate für Stereo-Downmix-Spur in kbps
    "audio_processing": {
        "drc_enabled": False,
        "drc_scale": 1.0,
        "loudnorm_enabled": False,
        "loudnorm_i": -18.0,
        "loudnorm_lra": 11.0,
        "loudnorm_tp": -1.5,
    },
    "channel_rules": {
        "mono":        {"max_channels": 1, "target_codec": "aac",  "max_bitrate_k": 128},
        "stereo": {
            "max_channels": 2,
            "target_codec": "aac",
            "max_bitrate_k": 192,
            "copy_min_bitrate_k": 192,
            "copy_max_bitrate_k": 256,
        },
        "surround_51": {
            "max_channels": 6,
            "target_channels": 6,
            "target_codec": "eac3",
            "max_bitrate_k": 640,
            "copy_min_bitrate_k": 428,
            "copy_max_bitrate_k": 640,
            "downmix_mode": "never",
            "downmix_bitrate_k": 256,
        },
        "surround_71": {
            "max_channels": 8,
            "target_channels": 6,
            "target_codec": "eac3",
            "max_bitrate_k": 640,
            "copy_min_bitrate_k": 768,
            "copy_max_bitrate_k": 1536,
            "downmix_mode": "always",
            "downmix_target": "surround_51",
            "downmix_bitrate_k": 640,
        },
    },
    "transcode_rules": {
        "truehd":    {"target_codec": "eac3"},
        "dts":       {"target_codec": "eac3"},
        "dts-hd ma": {"target_codec": "eac3"},
        "dts-hd hra":{"target_codec": "eac3"},
        "flac":      {"target_codec": "eac3"},
        "pcm":       {"target_codec": "eac3"},
        "mp2":       {"target_codec": "aac"},
        "mp3":       {"target_codec": "aac"},
    },
}


def _normalize_surround_51_downmix_mode(value: Any) -> str:
    mode = str(value or "").strip().lower()
    if mode in {"always", "never", "below_bitrate"}:
        return mode
    return "never"


def normalize_surround_71_downmix_target(value: Any) -> str:
    target = str(value or "").strip().lower()
    if target in {"stereo", "2", "2.0", "2ch"}:
        return "stereo"
    if target in {"surround_51", "5.1", "6", "6ch"}:
        return "surround_51"
    return "surround_51"


def _normalize_copy_range(
    rule: dict[str, Any],
    *,
    target_default_k: int,
    min_default_k: int,
    max_default_k: int,
    maximum_k: int,
) -> None:
    target_k = _clamp_int(rule.get("max_bitrate_k", target_default_k), target_default_k, 32, maximum_k)
    min_k = _clamp_int(rule.get("copy_min_bitrate_k", min_default_k), min_default_k, 0, maximum_k)
    max_k = _clamp_int(rule.get("copy_max_bitrate_k", max_default_k), max_default_k, 0, maximum_k)
    if max_k < min_k:
        max_k = min_k
    rule["max_bitrate_k"] = target_k
    rule["copy_min_bitrate_k"] = min_k
    rule["copy_max_bitrate_k"] = max_k


def normalize_audio_processing_config(rules: dict[str, Any] | None) -> dict[str, Any]:
    """Normalisiert DRC- und Loudness-Regeln auf sichere Zahlenbereiche."""
    raw = dict((rules or {}).get("audio_processing") or {})
    defaults = dict(_DEFAULT_RULES["audio_processing"])
    merged = {**defaults, **raw}
    return {
        "drc_enabled": _safe_bool(merged.get("drc_enabled", False), False),
        "drc_scale": round(_clamp_float(merged.get("drc_scale"), 1.0, 0.0, 4.0), 1),
        "loudnorm_enabled": _safe_bool(merged.get("loudnorm_enabled", False), False),
        "loudnorm_i": round(_clamp_float(merged.get("loudnorm_i"), -18.0, -40.0, -5.0), 1),
        "loudnorm_lra": round(_clamp_float(merged.get("loudnorm_lra"), 11.0, 1.0, 50.0), 1),
        "loudnorm_tp": round(_clamp_float(merged.get("loudnorm_tp"), -1.5, -9.0, 0.0), 1),
    }


def _normalize_stereo_copy_range(rule: dict[str, Any]) -> None:
    _normalize_copy_range(
        rule,
        target_default_k=192,
        min_default_k=192,
        max_default_k=256,
        maximum_k=2048,
    )


def _channels_for_surround_71_target(value: Any) -> int:
    return 2 if normalize_surround_71_downmix_target(value) == "stereo" else 6
