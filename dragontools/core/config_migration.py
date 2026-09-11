# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .type_utils import _safe_bool, _safe_int as _type_safe_int
from .json_io import atomic_write_json


SCHEMA_VERSION_KEY = "_schema_version"

CURRENT_SCHEMA_VERSIONS: dict[str, int] = {
    "audio_rules": 4,
    "subtitle_rules": 6,
    "move_rules": 1,
    "renamer_rules": 1,
    "profiles": 3,
}

MIGRATION_LOG_PATH = Path.home() / "Documents" / "DragonTools" / "Logging" / "MIGRATION" / "config_migration.log"


@dataclass(frozen=True)
class MigrationResult:
    data: dict[str, Any]
    changed: bool
    from_version: int
    to_version: int
    messages: tuple[str, ...] = ()


def schema_version(data: Any) -> int:
    if not isinstance(data, dict):
        return 0
    value = data.get(SCHEMA_VERSION_KEY)
    try:
        return max(0, int(value))
    except Exception:
        return 0


def current_schema_version(config_name: str) -> int:
    return int(CURRENT_SCHEMA_VERSIONS.get(config_name, 1))


def sanitize_config_for_persistence(data: dict[str, Any]) -> dict[str, Any]:
    """Entfernt nur flüchtige interne Top-Level-Felder vor dem Speichern."""
    clean: dict[str, Any] = {}
    for key, value in data.items():
        key_text = str(key)
        if key_text.startswith("_") and key_text != SCHEMA_VERSION_KEY:
            continue
        clean[key_text] = value
    return clean


def write_json_atomic(path: str | Path, data: dict[str, Any]) -> None:
    """Persistiert Konfigurationen crash-robust über den zentralen JSON-Writer.

    Die frühere lokale Implementierung nutzte zwar eine Tempdatei, aber kein
    ``fsync`` und einen festen ``.tmp``-Namen. Der gemeinsame Writer verwendet
    eindeutige Tempdateien, flush/fsync und ``os.replace`` und ist damit auch
    bei parallelen bzw. abrupt beendeten Schreibvorgängen belastbarer.
    """
    atomic_write_json(Path(path), data)


def log_config_migration(
    config_name: str,
    from_version: int,
    to_version: int,
    messages: list[str] | tuple[str, ...] | None = None,
    *,
    source_path: str | Path | None = None,
    reporter: Callable | None = None,
) -> None:
    msg_parts = [
        f"{config_name}: Schema {from_version} -> {to_version}",
    ]
    if source_path:
        msg_parts.append(f"Quelle: {source_path}")
    if messages:
        msg_parts.append("Änderungen: " + "; ".join(str(item) for item in messages if item))
    line = " | ".join(msg_parts)

    try:
        MIGRATION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(MIGRATION_LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(f"[{ts}] {line}\n")
    except Exception:
        pass

    try:
        from .audit_log import append_audit_event

        append_audit_event("Regel-/Profilmigration", line)
    except Exception:
        pass

    if reporter is None:
        return
    try:
        reporter(f"Regel-/Profilmigration: {line}", "info")
        return
    except TypeError:
        pass
    except Exception:
        return
    try:
        reporter(f"Regel-/Profilmigration: {line}")
    except Exception:
        pass


def finish_migration(
    config_name: str,
    data: dict[str, Any],
    *,
    raw: dict[str, Any] | None = None,
    messages: list[str] | tuple[str, ...] | None = None,
    source_path: str | Path | None = None,
    reporter: Callable | None = None,
) -> MigrationResult:
    result = dict(data or {})
    from_version = schema_version(raw if raw is not None else data)
    to_version = current_schema_version(config_name)
    if result.get(SCHEMA_VERSION_KEY) != to_version:
        result[SCHEMA_VERSION_KEY] = to_version
    msg_tuple = tuple(str(item) for item in (messages or ()) if str(item).strip())
    baseline = raw if raw is not None else data
    persistent_result = sanitize_config_for_persistence(result)
    persistent_baseline = sanitize_config_for_persistence(
        dict(baseline or {}) if isinstance(baseline, dict) else {}
    )
    changed = (
        from_version < to_version
        or bool(msg_tuple)
        or persistent_result != persistent_baseline
    )
    if changed and (source_path is not None or reporter is not None):
        log_config_migration(
            config_name,
            from_version,
            to_version,
            msg_tuple,
            source_path=source_path,
            reporter=reporter,
        )
    return MigrationResult(
        data=result,
        changed=changed,
        from_version=from_version,
        to_version=to_version,
        messages=msg_tuple,
    )


def _safe_int(value: Any, default: int) -> int:
    value_int = _type_safe_int(value, default)
    return default if value_int is None else value_int


def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    value_int = _safe_int(value, default)
    return max(minimum, min(maximum, value_int))


def _codec_from_profile_name(name: str, fallback: str = "h265") -> str:
    text = str(name or "").lower()
    if "h264" in text:
        return "h264"
    if "av1" in text:
        return "av1"
    if "h265" in text or "hevc" in text:
        return "h265"
    return fallback


def _default_encoder_options(encoder: str, codec: str, crf: int) -> dict[str, Any]:
    encoder = (encoder or "cpu").lower()
    if encoder == "nvenc":
        return {
            "encoder": "nvenc",
            "preset": "p6",
            "cq": crf,
            "bf": 4,
            "bref_mode": "middle",
            "rc_lookahead": 32,
            "lookahead_level": "auto",
            "multipass": "auto",
            "aq_strength": 8,
            "spatial_aq": True,
            "temporal_aq": True,
        }
    if encoder == "qsv":
        return {
            "encoder": "qsv",
            "preset": "medium",
            "q": crf,
            "lookahead_depth": 40,
        }
    if encoder == "amf":
        return {
            "encoder": "amf",
            "quality": "balanced",
            "qp": crf,
        }
    if codec == "av1":
        return {"encoder": "cpu"}
    return {
        "encoder": "cpu",
        "tune": "none",
        "aq_mode": "2",
        "aq_strength": "1.0",
        "psy_rd": "2.0",
        "psy_rdoq": "1.0",
        "bf": 8,
        "rc_lookahead": 40,
    }


def migrate_encoder_profile(
    key: str,
    profile: Any,
    *,
    default_codec: str = "h265",
) -> tuple[dict[str, Any], list[str]]:
    messages: list[str] = []
    raw = dict(profile) if isinstance(profile, dict) else {}
    if not isinstance(profile, dict):
        messages.append(f"Profil '{key}' war kein Objekt und wurde neu aufgebaut")

    codec = str(raw.get("codec") or _codec_from_profile_name(key, default_codec)).lower()
    if codec not in {"h264", "h265", "av1"}:
        codec = default_codec
        messages.append(f"Profil '{key}': Codec auf {default_codec} gesetzt")

    options = dict(raw.get("encoder_options") or {})
    encoder = str(options.get("encoder") or "cpu").strip().lower()
    allowed_encoders = {"cpu", "nvenc", "qsv", "amf"}
    if encoder not in allowed_encoders:
        messages.append(f"Profil '{key}': unbekannten Encoder '{encoder}' auf cpu gesetzt")
        encoder = "cpu"
    options["encoder"] = encoder
    # Der neue H.265-Werkstandard CRF 22 gilt gezielt für CPU/x265.
    # GPU-Profile behalten ihren bisherigen generischen Fallback 23.
    if codec == "h265":
        crf_default = 22 if encoder == "cpu" else 23
    else:
        crf_default = {"h264": 22, "av1": 28}.get(codec, 23)
    crf = _safe_int(raw.get("crf"), crf_default)
    preset = str(raw.get("preset") or ("6" if codec == "av1" else "medium"))
    scale = raw.get("scale")
    if not scale:
        scale = "original"
        messages.append(f"Profil '{key}': Skalierung auf original ergänzt")

    defaults = _default_encoder_options(encoder, codec, crf)
    if encoder == "qsv" and "lookahead" in options:
        options.pop("lookahead", None)
        messages.append(f"Profil '{key}': veraltete QSV-Option 'lookahead' entfernt")
    for opt_key, opt_value in defaults.items():
        if opt_key not in options:
            options[opt_key] = opt_value
            messages.append(f"Profil '{key}': Encoder-Option '{opt_key}' ergänzt")

    # Legacy-/QSettings-Zahlen und Bool-Strings backend-spezifisch kanonisieren.
    if encoder == "nvenc":
        for opt_key, fallback in (("cq", crf), ("bf", 4), ("rc_lookahead", 32), ("aq_strength", 8)):
            options[opt_key] = _safe_int(options.get(opt_key), fallback)
        options["spatial_aq"] = _safe_bool(options.get("spatial_aq"), True)
        options["temporal_aq"] = _safe_bool(options.get("temporal_aq"), True)
    elif encoder == "qsv":
        options["q"] = _safe_int(options.get("q"), crf)
        options["lookahead_depth"] = _clamp_int(options.get("lookahead_depth"), 40, 1, 100)
    elif encoder == "amf":
        options["qp"] = _safe_int(options.get("qp"), crf)
    elif encoder == "cpu":
        options["bf"] = _safe_int(options.get("bf"), 8)
        options["rc_lookahead"] = _safe_int(options.get("rc_lookahead"), 40)

    migrated = dict(raw)
    if not migrated.get("label"):
        migrated["label"] = str(key)
        messages.append(f"Profil '{key}': Label ergänzt")
    migrated["codec"] = codec
    migrated["crf"] = crf
    migrated["preset"] = preset
    migrated["scale"] = scale
    migrated["encoder_options"] = options
    return migrated, messages


def migrate_profile_collection(
    raw: Any,
    *,
    default_codec: str = "h265",
    source_path: str | Path | None = None,
    reporter: Callable | None = None,
) -> MigrationResult:
    data = dict(raw) if isinstance(raw, dict) else {}
    messages: list[str] = []
    if not isinstance(raw, dict):
        messages.append("Profil-Datei war kein JSON-Objekt und wurde neu aufgebaut")

    migrated: dict[str, Any] = {}
    for key, value in data.items():
        key_text = str(key)
        if key_text.startswith("_"):
            continue
        if not isinstance(value, dict):
            messages.append(f"Profil '{key_text}' übersprungen: kein Objekt")
            continue
        profile, profile_messages = migrate_encoder_profile(
            key_text,
            value,
            default_codec=default_codec,
        )
        migrated[key_text] = profile
        messages.extend(profile_messages)

    return finish_migration(
        "profiles",
        migrated,
        raw=data,
        messages=messages,
        source_path=source_path,
        reporter=reporter,
    )
