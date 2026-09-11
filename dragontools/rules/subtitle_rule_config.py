"""Schema, Standardwerte und Migration der Untertitelregeln."""
from __future__ import annotations

from typing import Any

from ..core.config_migration import SCHEMA_VERSION_KEY, finish_migration
from ..core.lang_codes import canonical_lang, language_aliases, normalize_language_priority
from ..core.type_utils import _safe_bool


TEXT_SUBTITLE_CODECS = {"subrip", "ass", "ssa", "subt", "mov_text", "tx3g", "webvtt", "srt", "text"}
IMAGE_SUBTITLE_CODECS = {"hdmv_pgs_subtitle", "dvd_subtitle", "vobsub"}
COMPATIBLE_SUBTITLE_CODECS = TEXT_SUBTITLE_CODECS | IMAGE_SUBTITLE_CODECS
GERMAN_LANGUAGE_CODES = language_aliases("de")
ENGLISH_LANGUAGE_CODES = language_aliases("en")
DEFAULT_PREFERRED_SUBTITLE_FORMATS = [
    "subrip", "srt",
    "ass", "ssa",
    "subt", "mov_text", "tx3g", "webvtt", "text",
    "hdmv_pgs_subtitle", "dvd_subtitle", "vobsub",
]


DEFAULT_SUBTITLE_RULES: dict[str, Any] = {
    SCHEMA_VERSION_KEY: 6,
    "language_priority": ["de", "en"],
    "max_languages": 1,
    "tracks_per_language": 1,
    "fallback_if_no_priority_match": "keep_none",
    "preferred_languages": ["de", "deu", "ger"],
    "fallback_languages": ["en", "eng"],
    "force_priority": True,
    "preferred_formats": list(DEFAULT_PREFERRED_SUBTITLE_FORMATS),
    "burn_in_rules": {
        "auto_burn_forced": True,
        "burn_language": "de",
        "burn_fallback": "none",
        "ask_if_ambiguous": True,
        "never_burn_if_no_audio_language": False,
        "never_burn_if_no_german_audio": False,
        "forced_plausibility": {
            "enabled": True,
            "warn_events_per_minute": 3.0,
            "block_events_per_minute": 5.0,
        },
    },
    "keep_rules": {
        "keep_forced": True,
        "keep_selected_languages": True,
        "keep_regular": True,
        "keep_if_no_burn_only": False,
        "keep_all_german": True,
        "keep_german_if_no_burn": False,
        "keep_english_fallback": False,
    },
    "mp4_sidecars_enabled": True,
    "additional_sidecars_enabled": False,
    "text_to_srt_sidecar_enabled": False,
}


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


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", "N/A"):
            return default
        return float(str(value).replace(",", "."))
    except Exception:
        return default


def normalize_forced_plausibility(raw: Any) -> dict[str, Any]:
    default = DEFAULT_SUBTITLE_RULES["burn_in_rules"]["forced_plausibility"]
    if not isinstance(raw, dict):
        raw = {}
    enabled = _safe_bool(raw.get("enabled"), default["enabled"])
    warn = max(0.0, safe_float(raw.get("warn_events_per_minute"), default["warn_events_per_minute"]))
    block = max(warn, safe_float(raw.get("block_events_per_minute"), default["block_events_per_minute"]))
    return {
        "enabled": enabled,
        "warn_events_per_minute": round(warn, 2),
        "block_events_per_minute": round(block, 2),
    }


def migrate_subtitle_rules(
    rules: dict[str, Any] | None,
    *,
    source_path: str | None = None,
    reporter: Any = None,
) -> dict[str, Any]:
    """Fuehrt alte Regeldateien auf das aktuelle Untertitelschema zusammen."""
    raw = dict(rules or {})
    migrated = dict(raw)
    migration_messages: list[str] = []
    legacy_language_rules = not any(
        key in raw
        for key in ("language_priority", "max_languages", "tracks_per_language", "fallback_if_no_priority_match")
    )

    legacy_priority = (
        normalize_language_priority(raw.get("preferred_languages"))
        + normalize_language_priority(raw.get("fallback_languages"))
    )
    priority = normalize_language_priority(raw.get("language_priority") or legacy_priority)
    if not priority:
        priority = list(DEFAULT_SUBTITLE_RULES["language_priority"])
        migration_messages.append("Untertitel-Sprachpriorität ergänzt")
    migrated["language_priority"] = priority
    migrated["max_languages"] = max(0, safe_int(raw.get("max_languages", 1), 1))
    migrated["tracks_per_language"] = max(0, safe_int(raw.get("tracks_per_language", 1), 1))
    migrated["fallback_if_no_priority_match"] = str(
        raw.get("fallback_if_no_priority_match", DEFAULT_SUBTITLE_RULES["fallback_if_no_priority_match"])
    )
    if "preferred_languages" not in raw:
        migration_messages.append("Legacy-Sprache bevorzugt ergänzt")
    if "fallback_languages" not in raw:
        migration_messages.append("Legacy-Fallbacksprache ergänzt")
    if "preferred_formats" not in raw:
        migration_messages.append("Untertitel-Formatpriorität ergänzt")
    if "force_priority" not in raw:
        migration_messages.append("Untertitel-Prioritätsflag ergänzt")
    if "mp4_sidecars_enabled" not in raw:
        if "dv_extract_external_subs" in raw:
            migration_messages.append("Legacy-DV-Sidecar-Regel in globale MP4-Sidecar-Regel übernommen")
        else:
            migration_messages.append("MP4-Sidecar-Regel ergänzt")
    if "additional_sidecars_enabled" not in raw:
        migration_messages.append("Zusätzliche Sidecar-Regel ergänzt")
    if "text_to_srt_sidecar_enabled" not in raw:
        if "ass_to_srt_sidecar_enabled" in raw:
            migration_messages.append("ASS/SSA-zu-SRT-Regel in Text-zu-SRT-Sidecar-Regel übernommen")
        else:
            migration_messages.append("Text-zu-SRT-Sidecar-Regel ergänzt")
    migrated.setdefault("preferred_languages", [priority[0]] if priority else ["de"])
    migrated.setdefault("fallback_languages", priority[1:] if len(priority) > 1 else ["en"])
    migrated.setdefault("preferred_formats", list(DEFAULT_SUBTITLE_RULES["preferred_formats"]))
    migrated["force_priority"] = _safe_bool(
        raw.get("force_priority"), DEFAULT_SUBTITLE_RULES["force_priority"]
    )
    legacy_mp4_sidecars = raw.get("dv_extract_external_subs")
    migrated["mp4_sidecars_enabled"] = _safe_bool(
        raw.get("mp4_sidecars_enabled", legacy_mp4_sidecars),
        DEFAULT_SUBTITLE_RULES["mp4_sidecars_enabled"],
    )
    migrated["additional_sidecars_enabled"] = _safe_bool(
        raw.get("additional_sidecars_enabled"),
        DEFAULT_SUBTITLE_RULES["additional_sidecars_enabled"],
    )
    migrated["text_to_srt_sidecar_enabled"] = _safe_bool(
        raw.get("text_to_srt_sidecar_enabled", raw.get("ass_to_srt_sidecar_enabled")),
        DEFAULT_SUBTITLE_RULES["text_to_srt_sidecar_enabled"],
    )
    migrated.pop("ass_to_srt_sidecar_enabled", None)
    if "dv_extract_external_subs" in raw:
        migrated["dv_extract_external_subs"] = migrated["mp4_sidecars_enabled"]

    burn_rules = dict(DEFAULT_SUBTITLE_RULES["burn_in_rules"])
    raw_burn_rules = raw.get("burn_in_rules") if isinstance(raw.get("burn_in_rules"), dict) else {}
    if isinstance(raw.get("burn_in_rules"), dict):
        burn_rules.update(raw["burn_in_rules"])
    else:
        migration_messages.append("Burn-In-Regeln ergänzt")
    for bool_key in (
        "auto_burn_forced",
        "ask_if_ambiguous",
        "never_burn_if_no_audio_language",
        "never_burn_if_no_german_audio",
    ):
        burn_rules[bool_key] = _safe_bool(
            burn_rules.get(bool_key), DEFAULT_SUBTITLE_RULES["burn_in_rules"].get(bool_key, False)
        )
    if "burn_language" not in burn_rules or not burn_rules.get("burn_language"):
        burn_rules["burn_language"] = priority[0] if priority else "de"
    burn_rules["burn_language"] = canonical_lang(burn_rules.get("burn_language")) or "de"
    if "never_burn_if_no_audio_language" not in raw_burn_rules and "never_burn_if_no_german_audio" in raw_burn_rules:
        burn_rules["never_burn_if_no_audio_language"] = _safe_bool(
            raw_burn_rules.get("never_burn_if_no_german_audio"), False
        )
        migration_messages.append("Burn-In-Regel für fehlende Audio-Sprache aus Legacy-Regel übernommen")
    if "forced_plausibility" not in raw_burn_rules:
        migration_messages.append("Forced-Plausibilitätsprüfung ergänzt")
    burn_rules["forced_plausibility"] = normalize_forced_plausibility(
        burn_rules.get("forced_plausibility")
    )
    migrated["burn_in_rules"] = burn_rules

    keep_rules = dict(DEFAULT_SUBTITLE_RULES["keep_rules"])
    if isinstance(raw.get("keep_rules"), dict):
        keep_rules.update(raw["keep_rules"])
    else:
        migration_messages.append("Keep-Regeln ergänzt")
    for bool_key, default_value in DEFAULT_SUBTITLE_RULES["keep_rules"].items():
        keep_rules[bool_key] = _safe_bool(keep_rules.get(bool_key), default_value)
    raw_keep_rules = raw.get("keep_rules") if isinstance(raw.get("keep_rules"), dict) else {}
    if legacy_language_rules and "keep_selected_languages" not in raw_keep_rules:
        keep_rules["keep_selected_languages"] = any(
            (
                keep_rules.get("keep_all_german", True),
                keep_rules.get("keep_german_if_no_burn", False),
                keep_rules.get("keep_english_fallback", False),
            )
        )
    migrated["keep_rules"] = keep_rules
    migrated["_legacy_language_rules"] = legacy_language_rules
    return finish_migration(
        "subtitle_rules",
        migrated,
        raw=raw,
        messages=migration_messages,
        source_path=source_path,
        reporter=reporter,
    ).data
