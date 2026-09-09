# -*- coding: utf-8 -*-
"""Channel mapping and transcode/passthrough policy for audio streams."""
from __future__ import annotations

from typing import Any

from ..core.models import AudioStream
from .audio_rule_basics import (
    _DEFAULT_RULES,
    _channels_for_surround_71_target,
    _clamp_int,
    _normalize_surround_51_downmix_mode,
    clamp_audio_target_to_codec_cap,
    max_channels_for_audio_codec,
    normalize_audio_codec,
    safe_int,
)
from .audio_rule_migration import migrate_audio_rules
from .audio_rule_repository import _load_rules

def _channel_rule(channels: int, rules: dict) -> dict:
    """
    Gibt die passende channel_rule zurück basierend auf der Kanalzahl.
    Reihenfolge: surround_71 (>6), surround_51 (>2), stereo (2), mono (1)
    """
    cr = migrate_audio_rules(rules).get("channel_rules", _DEFAULT_RULES["channel_rules"])

    r71 = cr.get("surround_71", {})
    r51 = cr.get("surround_51", {})
    r20 = cr.get("stereo", {})
    r10 = cr.get("mono", {})

    max_51 = safe_int(r51.get("max_channels"), 6)

    if channels > max_51:
        return r71
    if channels > 2:
        return r51
    if channels == 1:
        return r10
    return r20


def _surround_51_target_channels(channels: int, bitrate: int, rule: dict[str, Any]) -> int:
    mode = _normalize_surround_51_downmix_mode(rule.get("downmix_mode"))
    if mode == "always":
        return 2
    if mode == "below_bitrate":
        limit_bps = _clamp_int(rule.get("downmix_bitrate_k", 256), 256, 64, 2048) * 1000
        if bitrate > 0 and bitrate <= limit_bps:
            return 2
    return min(channels, safe_int(rule.get("max_channels"), 6))


def _surround_71_target_channels(channels: int, bitrate: int, rule: dict[str, Any]) -> int:
    mode = _normalize_surround_51_downmix_mode(rule.get("downmix_mode"))
    target_channels = _channels_for_surround_71_target(rule.get("downmix_target", rule.get("target_channels", 6)))
    if mode == "always":
        return target_channels
    if mode == "below_bitrate":
        limit_bps = _clamp_int(rule.get("downmix_bitrate_k", rule.get("max_bitrate_k", 640)), 640, 64, 4096) * 1000
        if bitrate > 0 and bitrate <= limit_bps:
            return target_channels
    return channels


def _surround_51_forces_downmix(bitrate: int, rule: dict[str, Any]) -> bool:
    mode = _normalize_surround_51_downmix_mode(rule.get("downmix_mode"))
    if mode == "always":
        return True
    if mode == "below_bitrate":
        limit_bps = _clamp_int(rule.get("downmix_bitrate_k", 256), 256, 64, 2048) * 1000
        return bitrate > 0 and bitrate <= limit_bps
    return False


def _surround_71_forces_downmix(bitrate: int, rule: dict[str, Any]) -> bool:
    mode = _normalize_surround_51_downmix_mode(rule.get("downmix_mode"))
    if mode == "always":
        return True
    if mode == "below_bitrate":
        limit_bps = _clamp_int(rule.get("downmix_bitrate_k", rule.get("max_bitrate_k", 640)), 640, 64, 4096) * 1000
        return bitrate > 0 and bitrate <= limit_bps
    return False


def _channel_rule_forces_downmix(channels: int, bitrate: int, rules: dict[str, Any], rule: dict[str, Any]) -> bool:
    s51_max = safe_int(rules.get("channel_rules", {}).get("surround_51", {}).get("max_channels"), 6)
    if 2 < channels <= s51_max:
        return _surround_51_forces_downmix(bitrate, rule)
    if channels > s51_max:
        return _surround_71_forces_downmix(bitrate, rule)
    return False


def _stereo_downmix_fallback_codec(rules: dict[str, Any]) -> str:
    stereo_rule = dict(rules.get("channel_rules", {}).get("stereo") or {})
    codec = normalize_audio_codec(str(stereo_rule.get("target_codec") or ""))
    if codec and codec != "copy":
        return codec
    return str(_DEFAULT_RULES["channel_rules"]["stereo"]["target_codec"])


def _surround_downmix_fallback_codec(rules: dict[str, Any], target_channels: int) -> str:
    if target_channels <= 2:
        return _stereo_downmix_fallback_codec(rules)
    surround_rule = dict(rules.get("channel_rules", {}).get("surround_51") or {})
    codec = normalize_audio_codec(str(surround_rule.get("target_codec") or ""))
    if codec and codec != "copy":
        return codec
    return str(_DEFAULT_RULES["channel_rules"]["surround_51"]["target_codec"])


def _force_codec_if_needed_for_channel_cap(target_codec: str, target_channels: int, channels: int, rules: dict[str, Any]) -> str:
    codec_norm = normalize_audio_codec(str(target_codec))
    if codec_norm == "copy" and target_channels < channels:
        return _surround_downmix_fallback_codec(rules, target_channels)
    return target_codec


def default_transcode_target(
    channels: int,
    bitrate: int = 0,
    rules: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the configured transcode target for a channel count."""
    rules = migrate_audio_rules(rules or _DEFAULT_RULES)
    cr = _channel_rule(channels, rules)
    max_bps = safe_int(cr.get("max_bitrate_k"), 640) * 1000
    s51_max = safe_int(rules.get("channel_rules", {}).get("surround_51", {}).get("max_channels"), 6)
    if 2 < channels <= s51_max:
        target_channels = _surround_51_target_channels(channels, bitrate, cr)
    else:
        target_channels = _surround_71_target_channels(channels, bitrate, cr)
    # Stereo darf beim Transkodieren nicht künstlich auf die konfigurierte
    # Zielbitrate hochgerechnet werden: aus z.B. MP3 128 kbps werden AAC
    # 128 kbps, während höhere Quellen weiterhin auf max_bps begrenzt werden.
    # Mono behält vorerst die bestehende feste Zielbitrate.
    if channels == 2:
        target_bps = bitrate if (0 < bitrate <= max_bps) else max_bps
    elif channels == 1:
        target_bps = max_bps
    else:
        target_bps = bitrate if (0 < bitrate <= max_bps) else max_bps
    target_codec = cr.get("target_codec", "eac3")
    target_codec = _force_codec_if_needed_for_channel_cap(target_codec, target_channels, channels, rules)
    return clamp_audio_target_to_codec_cap({
        "codec": target_codec,
        "channels": target_channels,
        "bitrate": target_bps,
    }, channels)


def _passthrough_bitrate_allowed(channels: int, bitrate: int, rule: dict[str, Any], max_bps: int) -> bool:
    if bitrate == 0:
        return True
    if any(key in rule for key in ("copy_min_bitrate_k", "copy_max_bitrate_k")):
        min_bps = _clamp_int(rule.get("copy_min_bitrate_k", 192), 192, 0, 4096) * 1000
        max_copy_bps = _clamp_int(rule.get("copy_max_bitrate_k", 256), 256, 0, 4096) * 1000
        if max_copy_bps < min_bps:
            max_copy_bps = min_bps
        return min_bps <= bitrate <= max_copy_bps
    return bitrate <= max_bps


def audio_requires_transcode(
    audio_stream: AudioStream,
    rules: dict | None = None,
) -> tuple[bool, dict[str, Any]]:
    """
    Entscheidet ob transkodiert werden muss und gibt das Ziel zurück.

    Rückgabe: (needs_transcode, target)
    target = {"codec": str, "channels": int, "bitrate": int (in bps)}
    """
    if rules is None:
        rules = _load_rules()
    else:
        rules = migrate_audio_rules(rules)

    codec_norm = normalize_audio_codec(audio_stream.codec)
    channels   = safe_int(audio_stream.channels, 2)
    bitrate    = safe_int(audio_stream.bitrate, 0)

    cr         = _channel_rule(channels, rules)
    max_bps    = safe_int(cr.get("max_bitrate_k"), 640) * 1000
    target     = default_transcode_target(channels, bitrate, rules)

    # 1) Immer transkodieren: Codec in transcode_rules
    trans_rules = rules.get("transcode_rules", _DEFAULT_RULES["transcode_rules"])
    if codec_norm in trans_rules:
        if channels <= 2:
            return True, target
        override_codec = trans_rules[codec_norm].get("target_codec", target["codec"])
        target["codec"] = override_codec
        target = clamp_audio_target_to_codec_cap(target, channels)
        return True, target

    # Kanal-Regel erzwingt einen Downmix (z.B. 5.1 -> AAC Stereo).
    # Stream-Copy kann keine Kanalzahl ändern, daher bleibt "copy" unangetastet.
    forced_downmix = _channel_rule_forces_downmix(channels, bitrate, rules, cr)
    if (
        forced_downmix
        and
        safe_int(target.get("channels"), channels) < channels
        and normalize_audio_codec(str(target.get("codec", ""))) != "copy"
    ):
        return True, target

    # 2) Passthrough möglich: Codec in passthrough_codecs
    passthrough = rules.get("passthrough_codecs", ["aac", "ac3", "eac3"])
    if codec_norm in passthrough:
        if _passthrough_bitrate_allowed(channels, bitrate, cr, max_bps):
            # Bitrate in Ordnung → kopieren
            return False, {"codec": "copy", "channels": channels, "bitrate": bitrate}
        else:
            # Bitrate zu hoch → auf Ziel-Codec runter
            return True, target

    # 3) Alles andere → transkodieren
    return True, target
