from __future__ import annotations

from typing import Any
from copy import deepcopy
import re

from .type_utils import _safe_bool, _safe_int
from .encoder_profile_override import runtime_encoder_capabilities
from .preflight_metadata_identity import normalize_metadata_context


def _runtime_fields(override: dict) -> dict:
    capabilities = runtime_encoder_capabilities(override)
    result = {"_encoder_runtime_capabilities": capabilities} if capabilities else {}
    metadata = normalize_metadata_context(override.get('metadata_context'))
    if metadata is not None:
        result['metadata_context'] = metadata
    return result


def _stream_index(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    text = str(value).strip()
    # Old settings stored integer indices as decimal strings such as '1.0'.
    # Accept only an all-zero fraction, never round or truncate an index.
    if not re.fullmatch(r"[0-9]+(?:\.0+)?", text):
        return None
    try:
        return int(text.split('.', 1)[0])
    except ValueError:
        return None


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value in (None, "", "N/A"):
            return default
        return float(str(value).replace(",", "."))
    except Exception:
        return default


def _normalize_mode(
    value: Any,
    *,
    allowed: set[str],
    default: str,
    legacy_custom: bool = False,
) -> str:
    mode = str(value or "").lower() if value is not None else ""
    if mode in allowed:
        return mode
    if legacy_custom and "custom" in allowed:
        return "custom"
    return default


def _normalize_processing_mode(override: dict[str, Any]) -> str:
    raw = override.get("processing_mode")
    strip_only = _safe_bool(override.get("strip_only"), False)
    if raw is None and strip_only:
        return "strip_only"
    mode = str(raw or "auto").lower()
    if mode in {"auto", "strip_only"}:
        return mode
    return "strip_only" if strip_only else "auto"


def _normalize_audio_tracks(override: dict[str, Any]) -> list[dict[str, Any]]:
    tracks: list[dict[str, Any]] = []
    for entry in list(override.get("audio_tracks", []) or []):
        if not isinstance(entry, dict):
            continue
        index = _stream_index(entry.get("index"))
        if index is None:
            continue
        mode = _normalize_mode(
            entry.get("mode", "auto"),
            allowed={"auto", "custom", "drop"},
            default="auto",
        )
        normalized: dict[str, Any] = {"index": index, "mode": mode}
        identity = entry.get("source_identity")
        if isinstance(identity, dict):
            normalized_identity = {
                "language": str(identity.get("language") or "").strip().lower(),
                "codec": str(identity.get("codec") or "").strip().lower(),
                "channels": _safe_int(identity.get("channels"), 0) or 0,
                "title": str(identity.get("title") or "").strip(),
            }
            if any(
                value not in ("", 0, None)
                for value in normalized_identity.values()
            ):
                normalized["source_identity"] = normalized_identity
        if mode == "custom":
            codec = entry.get("codec")
            normalized["codec"] = str(codec).lower() if codec not in (None, "") else None
            normalized["bitrate"] = _safe_int(entry.get("bitrate"))
        tracks.append(normalized)
    return tracks


def _normalize_subtitle_tracks(
    override: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    tracks: list[dict[str, Any]] = []
    warnings: list[str] = []
    burn_index: int | None = None
    ignored_burn_indices: list[int] = []

    for entry in list(override.get("subtitle_tracks", []) or []):
        if not isinstance(entry, dict):
            continue
        index = _stream_index(entry.get("index"))
        if index is None:
            continue
        normalized = {
            "index": index,
            "keep": _safe_bool(entry.get("keep"), False),
            "burn_in": _safe_bool(entry.get("burn_in"), False),
        }
        identity = entry.get("source_identity")
        if isinstance(identity, dict):
            normalized_identity = {
                "language": str(identity.get("language") or "").strip().lower(),
                "codec": str(identity.get("codec") or "").strip().lower(),
                "title": str(identity.get("title") or "").strip(),
            }
            if "forced" in identity:
                normalized_identity["forced"] = _safe_bool(identity.get("forced"), False)
            if "default" in identity:
                normalized_identity["default"] = _safe_bool(identity.get("default"), False)
            if any(
                value not in ("", None)
                for key, value in normalized_identity.items()
                if key not in {"forced", "default"}
            ) or "forced" in normalized_identity or "default" in normalized_identity:
                normalized["source_identity"] = normalized_identity
        if normalized["burn_in"] and burn_index is None:
            burn_index = index
        elif normalized["burn_in"]:
            normalized["burn_in"] = False
            ignored_burn_indices.append(index)
        tracks.append(normalized)

    if burn_index is not None:
        tracks = [
            {**entry, "keep": False} if entry["index"] == burn_index else entry
            for entry in tracks
        ]

    if ignored_burn_indices:
        ignored = ", ".join(f"#{index}" for index in ignored_burn_indices)
        warnings.append(
            "Nur eine Untertitelspur kann eingebrannt werden. "
            f"Spur(en) {ignored} (burn_in=True) werden ignoriert, "
            f"da Spur #{burn_index} bereits als Burn-In-Spur gesetzt ist."
        )
    return tracks, warnings


def _tristate(override: dict[str, Any], key: str) -> bool | None:
    value = override.get(key)
    if value is None:
        return None
    return _safe_bool(value, False)


def _dict_override(override: dict[str, Any], key: str) -> dict[str, Any] | None:
    value = override.get(key)
    return deepcopy(value) if isinstance(value, dict) and value else None


def _audio_processing_override(
    override: dict[str, Any],
    key: str,
    value_key: str,
    default_value: float,
) -> dict[str, Any] | None:
    raw = override.get(key)
    if not isinstance(raw, dict):
        return None
    mode = str(raw.get("mode", "inherit") or "inherit").lower()
    if mode not in {"inherit", "on", "off"}:
        mode = "inherit"
    if mode == "inherit":
        return None

    value = _safe_float(raw.get(value_key), default_value)
    if value is None:
        value = default_value
    if value_key == "scale":
        value = max(0.0, min(4.0, value))
    elif value_key == "i":
        value = max(-40.0, min(-5.0, value))
    return {"mode": mode, value_key: round(value, 1)}


def normalize_override_dict(file_override: dict[str, Any] | None) -> dict[str, Any]:
    """Kanonisiert Legacy- und aktuelle per-Datei-Overrides.

    Legacy-Felder werden nur als Eingabe interpretiert und unter ``_legacy``
    erhalten. Normalisierungswarnungen stehen immer als Liste unter
    ``_warnings``.
    """
    override = dict(file_override or {})
    existing_legacy = override.get("_legacy")
    if not isinstance(existing_legacy, dict):
        existing_legacy = {}
    legacy_audio_action = str(
        override.get("audio_action", existing_legacy.get("audio_action", "auto")) or "auto"
    ).lower()
    legacy_burn_mode = str(
        override.get("burn_mode", existing_legacy.get("burn_mode", "auto")) or "auto"
    ).lower()

    audio_mode = _normalize_mode(
        override.get("audio_mode"),
        allowed={"auto", "custom"},
        default="auto",
        legacy_custom=legacy_audio_action != "auto",
    )
    subtitle_mode = _normalize_mode(
        override.get("subtitle_mode"),
        allowed={"auto", "custom"},
        default="auto",
        legacy_custom=legacy_burn_mode != "auto",
    )
    subtitle_tracks, warnings = _normalize_subtitle_tracks(override)
    for warning in list(override.get("_warnings") or []):
        text = str(warning or "").strip()
        if text and text not in warnings:
            warnings.append(text)

    return {
        "audio_mode": audio_mode,
        **_runtime_fields(override),
        "audio_tracks": _normalize_audio_tracks(override),
        "subtitle_mode": subtitle_mode,
        "subtitle_tracks": subtitle_tracks,
        "processing_mode": _normalize_processing_mode(override),
        "imax": _safe_bool(override.get("imax", False), False),
        "preserve_dv": _tristate(override, "preserve_dv"),
        "preserve_hdrplus": _tristate(override, "preserve_hdrplus"),
        "sdr_hdr": _tristate(override, "sdr_hdr"),
        "generate_hdr10plus": _tristate(override, "generate_hdr10plus"),
        "allow_suspicious_source": _safe_bool(
            override.get("allow_suspicious_source", False), False
        ),
        "encoder_profile": _dict_override(override, "encoder_profile"),
        "encoder_override": _dict_override(override, "encoder_override"),
        "audio_drc": _audio_processing_override(override, "audio_drc", "scale", 1.0),
        "audio_loudnorm": _audio_processing_override(override, "audio_loudnorm", "i", -18.0),
        "_warnings": warnings,
        "_legacy": {
            "audio_action": legacy_audio_action,
            "burn_mode": legacy_burn_mode,
            "burn_stream_index": _stream_index(
                override.get("burn_stream_index", existing_legacy.get("burn_stream_index"))
            ),
        },
    }


__all__ = ["normalize_override_dict"]
