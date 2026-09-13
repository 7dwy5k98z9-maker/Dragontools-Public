# -*- coding: utf-8 -*-
"""Migration and normalization of persisted audio-rule configuration."""
from __future__ import annotations

from typing import Any

from ..core.config_migration import finish_migration
from ..core.lang_codes import normalize_language_priority
from ..core.type_utils import _safe_bool
from .audio_rule_basics import (
    _DEFAULT_RULES,
    _channels_for_surround_71_target,
    _clamp_int,
    _normalize_copy_range,
    _normalize_stereo_copy_range,
    _normalize_surround_51_downmix_mode,
    max_channels_for_audio_codec,
    normalize_audio_codec,
    normalize_audio_processing_config,
    normalize_surround_71_downmix_target,
    safe_int,
)

def _merged_channel_rule(name: str, rule: Any) -> dict[str, Any]:
    defaults = dict(_DEFAULT_RULES["channel_rules"][name])
    if isinstance(rule, dict):
        defaults.update(rule)
    return defaults


def _migrate_general_audio_settings(
    migrated: dict[str, Any],
    raw: dict[str, Any],
    messages: list[str],
) -> None:
    legacy_priority = (
        normalize_language_priority(migrated.get("preferred_languages"))
        + normalize_language_priority(migrated.get("fallback_languages"))
    )
    priority = normalize_language_priority(migrated.get("language_priority") or legacy_priority)
    if not priority:
        priority = list(_DEFAULT_RULES["language_priority"])
        messages.append("Audio-Sprachpriorität ergänzt")
    migrated["language_priority"] = priority

    max_languages_default = migrated.get("max_tracks", _DEFAULT_RULES["max_languages"])
    migrated["max_languages"] = max(
        0,
        safe_int(migrated.get("max_languages", max_languages_default), _DEFAULT_RULES["max_languages"]),
    )
    migrated["tracks_per_language"] = max(0, safe_int(migrated.get("tracks_per_language", 1), 1))
    migrated["fallback_if_no_priority_match"] = str(
        migrated.get("fallback_if_no_priority_match", _DEFAULT_RULES["fallback_if_no_priority_match"])
    )
    migrated["ignore_commentary_tracks"] = _safe_bool(
        migrated.get("ignore_commentary_tracks"), _DEFAULT_RULES["ignore_commentary_tracks"]
    )
    migrated["ignore_descriptive_audio"] = _safe_bool(
        migrated.get("ignore_descriptive_audio"), _DEFAULT_RULES["ignore_descriptive_audio"]
    )
    migrated["extra_stereo"] = _safe_bool(migrated.get("extra_stereo"), _DEFAULT_RULES["extra_stereo"])
    migrated["extra_stereo_bitrate_k"] = _clamp_int(
        migrated.get("extra_stereo_bitrate_k", _DEFAULT_RULES["extra_stereo_bitrate_k"]),
        _DEFAULT_RULES["extra_stereo_bitrate_k"], 64, 640,
    )
    codec = normalize_audio_codec(str(migrated.get("extra_stereo_codec", "aac") or "aac"))
    migrated["extra_stereo_codec"] = codec if codec in {"aac", "eac3", "ac3"} else "aac"

    missing_messages = {
        "extra_stereo": "Zusatz-Stereo-Downmix-Flag ergänzt",
        "extra_stereo_codec": "Codec für Zusatz-Stereo-Downmix ergänzt",
        "extra_stereo_bitrate_k": "Bitrate für Zusatz-Stereo-Downmix ergänzt",
        "audio_processing": "Audio-Dynamik / Lautheit ergänzt",
    }
    messages.extend(message for key, message in missing_messages.items() if key not in raw)
    migrated["audio_processing"] = normalize_audio_processing_config(migrated)
    migrated.setdefault("preferred_languages", [priority[0]] if priority else ["de"])
    migrated.setdefault("fallback_languages", priority[1:] if len(priority) > 1 else ["en"])
    migrated.setdefault("max_tracks", migrated["max_languages"])


def _rule_has_copy_range(rule: Any) -> bool:
    return isinstance(rule, dict) and (
        "copy_min_bitrate_k" in rule or "copy_max_bitrate_k" in rule
    )


def _migrate_mono_and_stereo(channel_rules: dict[str, Any], messages: list[str]) -> None:
    legacy_stereo = channel_rules.get("stereo") if isinstance(channel_rules.get("stereo"), dict) else None
    raw_stereo = legacy_stereo or {}
    raw_stereo_has_copy_range = _rule_has_copy_range(raw_stereo)

    if "mono" not in channel_rules:
        channel_rules["mono"] = dict(_DEFAULT_RULES["channel_rules"]["mono"])
        messages.append("Mono-Regel ergänzt")
    else:
        channel_rules["mono"] = _merged_channel_rule("mono", channel_rules["mono"])
    channel_rules["mono"]["max_channels"] = 1

    if "stereo" not in channel_rules:
        channel_rules["stereo"] = dict(legacy_stereo) if legacy_stereo else dict(_DEFAULT_RULES["channel_rules"]["stereo"])
        messages.append("Stereo-Regel ergänzt")
    else:
        channel_rules["stereo"] = _merged_channel_rule("stereo", channel_rules["stereo"])
    channel_rules["stereo"]["max_channels"] = 2
    if not raw_stereo_has_copy_range and safe_int(channel_rules["stereo"].get("max_bitrate_k"), 256) == 256:
        channel_rules["stereo"]["max_bitrate_k"] = 192
        messages.append("Stereo-Zielbitrate auf 192 kbps migriert")
    if not raw_stereo_has_copy_range:
        messages.append("Stereo-Kopierbereich 192-256 kbps ergänzt")
    _normalize_stereo_copy_range(channel_rules["stereo"])


def _migrate_surround_51(channel_rules: dict[str, Any], messages: list[str]) -> None:
    raw = channel_rules.get("surround_51") if isinstance(channel_rules.get("surround_51"), dict) else {}
    had_downmix_mode = "downmix_mode" in raw
    had_copy_range = _rule_has_copy_range(raw)
    if "surround_51" not in channel_rules:
        messages.append("surround_51-Regel ergänzt")
    s51 = _merged_channel_rule("surround_51", channel_rules.get("surround_51"))
    channel_rules["surround_51"] = s51
    s51["max_channels"] = 6
    if not had_downmix_mode:
        legacy_target_channels = safe_int(s51.get("target_channels"), 6)
        s51["downmix_mode"] = "always" if legacy_target_channels <= 2 else "never"
        messages.append("5.1-Downmix-Modus ergänzt")
    s51["downmix_mode"] = _normalize_surround_51_downmix_mode(s51.get("downmix_mode"))
    s51["downmix_bitrate_k"] = _clamp_int(s51.get("downmix_bitrate_k", 256), 256, 64, 2048)
    s51["target_channels"] = 2 if s51["downmix_mode"] == "always" else 6
    if not had_copy_range:
        messages.append("5.1-Kopierbereich 428-640 kbps ergänzt")
    _normalize_copy_range(s51, target_default_k=640, min_default_k=428, max_default_k=640, maximum_k=4096)


def _migrate_surround_71(channel_rules: dict[str, Any], messages: list[str]) -> None:
    raw = channel_rules.get("surround_71") if isinstance(channel_rules.get("surround_71"), dict) else {}
    had_downmix_mode = "downmix_mode" in raw
    had_copy_range = _rule_has_copy_range(raw)
    if "surround_71" not in channel_rules:
        messages.append("surround_71-Regel ergänzt")
    s71 = _merged_channel_rule("surround_71", channel_rules.get("surround_71"))
    channel_rules["surround_71"] = s71
    s71["max_channels"] = 8
    target_codec = normalize_audio_codec(str(s71.get("target_codec", "eac3") or "eac3"))
    if not had_downmix_mode:
        legacy_target_channels = safe_int(s71.get("target_channels"), 8)
        if legacy_target_channels <= 2:
            s71["downmix_mode"], s71["downmix_target"] = "always", "stereo"
        elif legacy_target_channels <= 6 or max_channels_for_audio_codec(target_codec) <= 6:
            s71["downmix_mode"], s71["downmix_target"] = "always", "surround_51"
        else:
            s71["downmix_mode"], s71["downmix_target"] = "never", "surround_51"
        messages.append("7.1-Downmix-Modus ergänzt")
    s71["downmix_mode"] = _normalize_surround_51_downmix_mode(s71.get("downmix_mode"))
    s71["downmix_target"] = normalize_surround_71_downmix_target(
        s71.get("downmix_target", s71.get("target_channels", 6))
    )
    s71["downmix_bitrate_k"] = _clamp_int(s71.get("downmix_bitrate_k", s71.get("max_bitrate_k", 640)), 640, 64, 4096)
    if not had_copy_range:
        messages.append("7.1-Kopierbereich 768-1536 kbps ergänzt")
    _normalize_copy_range(s71, target_default_k=640, min_default_k=768, max_default_k=1536, maximum_k=4096)
    target_channels = _channels_for_surround_71_target(s71["downmix_target"])
    if s71["downmix_mode"] == "never":
        target_channels = 8
    s71["target_channels"] = min(target_channels, max_channels_for_audio_codec(target_codec))


def _migrate_channel_rules(migrated: dict[str, Any], messages: list[str]) -> None:
    channel_rules = dict(migrated.get("channel_rules") or {})
    _migrate_mono_and_stereo(channel_rules, messages)
    _migrate_surround_51(channel_rules, messages)
    _migrate_surround_71(channel_rules, messages)
    migrated["channel_rules"] = channel_rules


def migrate_audio_rules(
    rules: dict[str, Any] | None,
    *,
    source_path: str | None = None,
    reporter: Any = None,
) -> dict[str, Any]:
    """Normalize persisted audio rules and migrate legacy channel policies."""
    raw = dict(rules or {})
    migrated = dict(raw)
    messages: list[str] = []
    _migrate_general_audio_settings(migrated, raw, messages)
    _migrate_channel_rules(migrated, messages)
    return finish_migration(
        "audio_rules",
        migrated,
        raw=raw,
        messages=messages,
        source_path=source_path,
        reporter=reporter,
    ).data
