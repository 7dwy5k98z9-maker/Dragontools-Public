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


def migrate_audio_rules(
    rules: dict[str, Any] | None,
    *,
    source_path: str | None = None,
    reporter: Any = None,
) -> dict[str, Any]:
    """Return audio rules with split mono/stereo channel rules filled in.

    Legacy configs only had ``channel_rules.stereo`` for 1-2 channels. Missing
    mono rules intentionally fall back to AAC/128k so mono tracks are not
    promoted to E-AC3 just because an old stereo rule used E-AC3.
    """
    raw = dict(rules or {})
    migrated = dict(raw)
    migration_messages: list[str] = []

    legacy_priority = (
        normalize_language_priority(migrated.get("preferred_languages"))
        + normalize_language_priority(migrated.get("fallback_languages"))
    )
    priority = normalize_language_priority(migrated.get("language_priority") or legacy_priority)
    if not priority:
        priority = list(_DEFAULT_RULES["language_priority"])
        migration_messages.append("Audio-Sprachpriorität ergänzt")
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
    migrated["extra_stereo"] = _safe_bool(
        migrated.get("extra_stereo"), _DEFAULT_RULES["extra_stereo"]
    )
    migrated["extra_stereo_bitrate_k"] = _clamp_int(
        migrated.get("extra_stereo_bitrate_k", _DEFAULT_RULES["extra_stereo_bitrate_k"]),
        _DEFAULT_RULES["extra_stereo_bitrate_k"], 64, 640,
    )
    extra_stereo_codec = normalize_audio_codec(str(migrated.get("extra_stereo_codec", "aac") or "aac"))
    migrated["extra_stereo_codec"] = extra_stereo_codec if extra_stereo_codec in {"aac", "eac3", "ac3"} else "aac"
    if "extra_stereo" not in raw:
        migration_messages.append("Zusatz-Stereo-Downmix-Flag ergänzt")
    if "extra_stereo_codec" not in raw:
        migration_messages.append("Codec für Zusatz-Stereo-Downmix ergänzt")
    if "extra_stereo_bitrate_k" not in raw:
        migration_messages.append("Bitrate für Zusatz-Stereo-Downmix ergänzt")
    if "audio_processing" not in raw:
        migration_messages.append("Audio-Dynamik / Lautheit ergänzt")
    migrated["audio_processing"] = normalize_audio_processing_config(migrated)
    migrated.setdefault("preferred_languages", [priority[0]] if priority else ["de"])
    migrated.setdefault("fallback_languages", priority[1:] if len(priority) > 1 else ["en"])
    migrated.setdefault("max_tracks", migrated["max_languages"])

    channel_rules = dict(migrated.get("channel_rules") or {})
    legacy_stereo = channel_rules.get("stereo") if isinstance(channel_rules.get("stereo"), dict) else None
    raw_stereo = legacy_stereo or {}
    raw_stereo_has_copy_range = (
        isinstance(raw_stereo, dict)
        and (
            "copy_min_bitrate_k" in raw_stereo
            or "copy_max_bitrate_k" in raw_stereo
        )
    )
    raw_s51 = channel_rules.get("surround_51") if isinstance(channel_rules.get("surround_51"), dict) else {}
    raw_s51_has_downmix_mode = "downmix_mode" in raw_s51
    raw_s51_has_copy_range = (
        isinstance(raw_s51, dict)
        and (
            "copy_min_bitrate_k" in raw_s51
            or "copy_max_bitrate_k" in raw_s51
        )
    )
    raw_s71 = channel_rules.get("surround_71") if isinstance(channel_rules.get("surround_71"), dict) else {}
    raw_s71_has_downmix_mode = "downmix_mode" in raw_s71
    raw_s71_has_copy_range = (
        isinstance(raw_s71, dict)
        and (
            "copy_min_bitrate_k" in raw_s71
            or "copy_max_bitrate_k" in raw_s71
        )
    )

    if "mono" not in channel_rules:
        channel_rules["mono"] = dict(_DEFAULT_RULES["channel_rules"]["mono"])
        channel_rules["mono"]["max_channels"] = 1
        migration_messages.append("Mono-Regel ergänzt")
    else:
        channel_rules["mono"] = _merged_channel_rule("mono", channel_rules["mono"])
        channel_rules["mono"]["max_channels"] = 1

    if "stereo" not in channel_rules:
        channel_rules["stereo"] = dict(legacy_stereo) if legacy_stereo else dict(_DEFAULT_RULES["channel_rules"]["stereo"])
        channel_rules["stereo"]["max_channels"] = 2
        migration_messages.append("Stereo-Regel ergänzt")
    else:
        channel_rules["stereo"] = _merged_channel_rule("stereo", channel_rules["stereo"])
        channel_rules["stereo"]["max_channels"] = 2
    if not raw_stereo_has_copy_range and safe_int(channel_rules["stereo"].get("max_bitrate_k"), 256) == 256:
        channel_rules["stereo"]["max_bitrate_k"] = 192
        migration_messages.append("Stereo-Zielbitrate auf 192 kbps migriert")
    if not raw_stereo_has_copy_range:
        migration_messages.append("Stereo-Kopierbereich 192-256 kbps ergänzt")
    _normalize_stereo_copy_range(channel_rules["stereo"])

    for name in ("surround_51", "surround_71"):
        if name not in channel_rules:
            migration_messages.append(f"{name}-Regel ergänzt")
        channel_rules[name] = _merged_channel_rule(name, channel_rules.get(name))
    channel_rules["surround_51"]["max_channels"] = 6
    s51 = channel_rules["surround_51"]
    if not raw_s51_has_downmix_mode:
        legacy_target_channels = safe_int(s51.get("target_channels"), 6)
        s51["downmix_mode"] = "always" if legacy_target_channels <= 2 else "never"
        migration_messages.append("5.1-Downmix-Modus ergänzt")
    s51["downmix_mode"] = _normalize_surround_51_downmix_mode(s51.get("downmix_mode"))
    s51["downmix_bitrate_k"] = _clamp_int(s51.get("downmix_bitrate_k", 256), 256, 64, 2048)
    s51["target_channels"] = 2 if s51["downmix_mode"] == "always" else 6
    if not raw_s51_has_copy_range:
        migration_messages.append("5.1-Kopierbereich 428-640 kbps ergänzt")
    _normalize_copy_range(
        s51,
        target_default_k=640,
        min_default_k=428,
        max_default_k=640,
        maximum_k=4096,
    )

    s71 = channel_rules["surround_71"]
    s71["max_channels"] = 8
    s71_target_codec = normalize_audio_codec(str(s71.get("target_codec", "eac3") or "eac3"))
    if not raw_s71_has_downmix_mode:
        legacy_target_channels = safe_int(s71.get("target_channels"), 8)
        if legacy_target_channels <= 2:
            s71["downmix_mode"] = "always"
            s71["downmix_target"] = "stereo"
        elif legacy_target_channels <= 6 or max_channels_for_audio_codec(s71_target_codec) <= 6:
            s71["downmix_mode"] = "always"
            s71["downmix_target"] = "surround_51"
        else:
            s71["downmix_mode"] = "never"
            s71["downmix_target"] = "surround_51"
        migration_messages.append("7.1-Downmix-Modus ergänzt")
    s71["downmix_mode"] = _normalize_surround_51_downmix_mode(s71.get("downmix_mode"))
    s71["downmix_target"] = normalize_surround_71_downmix_target(
        s71.get("downmix_target", s71.get("target_channels", 6))
    )
    s71["downmix_bitrate_k"] = _clamp_int(s71.get("downmix_bitrate_k", s71.get("max_bitrate_k", 640)), 640, 64, 4096)
    if not raw_s71_has_copy_range:
        migration_messages.append("7.1-Kopierbereich 768-1536 kbps ergänzt")
    _normalize_copy_range(
        s71,
        target_default_k=640,
        min_default_k=768,
        max_default_k=1536,
        maximum_k=4096,
    )
    s71_target_channels = _channels_for_surround_71_target(s71["downmix_target"])
    if s71["downmix_mode"] == "never":
        s71_target_channels = 8
    s71["target_channels"] = min(s71_target_channels, max_channels_for_audio_codec(s71_target_codec))

    migrated["channel_rules"] = channel_rules
    return finish_migration(
        "audio_rules",
        migrated,
        raw=raw,
        messages=migration_messages,
        source_path=source_path,
        reporter=reporter,
    ).data
