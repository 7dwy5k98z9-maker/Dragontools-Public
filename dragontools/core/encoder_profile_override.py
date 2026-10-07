from __future__ import annotations

from typing import Any
from copy import deepcopy

from .type_utils import _safe_bool, _safe_int


SCALE_LABELS_TO_MODE = {
    "original": "original",
    "4K (2160p)": "4k",
    "2160p": "4k",
    "4k": "4k",
    "1080p": "1080p",
    "720p": "720p",
    "480p": "480p",
}

MODE_TO_SCALE_LABEL = {
    "original": "original",
    "4k": "4K (2160p)",
    "1080p": "1080p",
    "720p": "720p",
    "480p": "480p",
}

_ALLOWED_ENCODERS = {"cpu", "nvenc", "qsv", "amf"}
_BACKEND_OPTIONS = frozenset({
    "encoder", "preset", "tune", "aq_mode", "aq_strength", "psy_rd", "psy_rdoq",
    "bf", "rc_lookahead", "cq", "spatial_aq", "temporal_aq", "lookahead_level",
    "multipass", "bref_mode", "q", "lookahead", "lookahead_depth", "quality", "qp",
})


def _merge_encoder_options(current: dict, incoming: dict, *, encoder: str | None = None) -> dict:
    active = str(current.get("encoder") or "cpu").strip().lower()
    selected = str(encoder or incoming.get("encoder") or active).strip().lower()
    # Feature policy/capability data belongs to the job; encoding parameters
    # belong to the selected backend, including names shared by two backends.
    retained = current if selected == active else {k: v for k, v in current.items() if k not in _BACKEND_OPTIONS}
    return {**deepcopy(retained), **deepcopy(incoming), "encoder": selected}


def _codec_text(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip().lower()


def _same_codec(profile_codec: Any, default_codec: str) -> bool:
    profile_value = _codec_text(profile_codec or default_codec)
    default_value = _codec_text(default_codec)
    return bool(profile_value) and profile_value == default_value



def _scale_mode(value: Any, fallback: str = "original") -> str:
    text = str(value or "").strip()
    if text in SCALE_LABELS_TO_MODE:
        return SCALE_LABELS_TO_MODE[text]
    lowered = text.lower()
    return SCALE_LABELS_TO_MODE.get(lowered, fallback)


def scoped_encoder_options(
    options: Any,
    *,
    active_encoder: str,
    target_encoder: str,
) -> dict[str, Any]:
    """Return options only for the backend they actually belong to.

    Encoder option names overlap between backends (for example ``aq_strength``,
    ``bf`` and ``rc_lookahead``). Loading one backend's option dictionary into
    another backend's widgets can therefore produce invalid conversions such as
    NVENC trying to parse x265's string value ``"1.0"`` as an integer.
    """
    active = str(active_encoder or "").strip().lower()
    target = str(target_encoder or "").strip().lower()
    if active != target or not isinstance(options, dict):
        return {}
    return dict(options)


def file_override_may_enable_encoder_option(override: Any, option: str) -> bool:
    """Conservative capability probe for options stored in per-file encoder profiles.

    Runtime capability discovery happens before a concrete file profile becomes
    effective.  It therefore only needs to know whether *any* queued override may
    request an optional feature.  Over-probing is safe; under-probing would make
    an otherwise valid assigned profile silently ineffective.
    """
    if not isinstance(override, dict):
        return False
    for key in ("encoder_override", "encoder_profile"):
        nested = override.get(key)
        if not isinstance(nested, dict):
            continue
        options = nested.get("encoder_options")
        if isinstance(options, dict) and _safe_bool(options.get(option, False), False):
            return True
    return False


def runtime_encoder_capabilities(override: dict) -> dict:
    """Owned per-file readiness facts cannot override encoding policy."""
    values = override.get("_encoder_runtime_capabilities")
    if not isinstance(values, dict):
        return {}
    return deepcopy({key: value for key, value in values.items()
                     if isinstance(key, str) and key.startswith("_comfyui_")})


def profile_to_override(
    key: str,
    profile: dict[str, Any],
    *,
    default_codec: str,
) -> dict[str, Any] | None:
    """Erzeugt ein kompaktes per-Datei-Profil für den Override-Speicher."""
    if not isinstance(profile, dict) or not _same_codec(profile.get("codec"), default_codec):
        return None

    encoder_options = profile.get("encoder_options")
    if not isinstance(encoder_options, dict):
        encoder_options = {}

    return {
        "key": str(key or "").strip(),
        "label": str(profile.get("label") or key or "Profil").strip(),
        "codec": _codec_text(profile.get("codec") or default_codec),
        "crf": _safe_int(profile.get("crf")),
        "preset": str(profile.get("preset") or "").strip(),
        "scale": str(profile.get("scale") or "original").strip(),
        "encoder_options": dict(encoder_options),
    }


def normalize_profile_override(
    profile: Any,
    *,
    default_codec: str,
) -> dict[str, Any] | None:
    """Validiert ein gespeichertes Profil-Override für die Worker-Nutzung."""
    if not isinstance(profile, dict) or not _same_codec(profile.get("codec"), default_codec):
        return None

    encoder_options = profile.get("encoder_options")
    if not isinstance(encoder_options, dict):
        encoder_options = {}

    return {
        "key": str(profile.get("key") or "").strip(),
        "label": str(profile.get("label") or profile.get("key") or "Profil").strip(),
        "codec": _codec_text(profile.get("codec") or default_codec),
        "crf": _safe_int(profile.get("crf")),
        "preset": str(profile.get("preset") or "").strip(),
        "scale": str(profile.get("scale") or "original").strip(),
        "encoder_options": dict(encoder_options),
    }


def normalize_encoder_override(
    override: Any,
    *,
    default_codec: str,
) -> dict[str, Any] | None:
    """Validiert die frei eingestellten Encoderwerte einer einzelnen Datei.

    Das Zielcodec bleibt absichtlich an den aktuellen Converter-Tab gebunden.
    Pro Datei dürfen Encoder-Backend, Qualität, Preset, Skalierung und die
    backend-spezifischen Optionen abweichen.
    """
    if not isinstance(override, dict) or not _same_codec(override.get("codec"), default_codec):
        return None

    encoder = str(override.get("encoder") or "").strip().lower()
    if encoder not in _ALLOWED_ENCODERS:
        return None

    encoder_options = override.get("encoder_options")
    if not isinstance(encoder_options, dict):
        encoder_options = {}
    encoder_options = dict(encoder_options)
    encoder_options["encoder"] = encoder

    quality = _safe_int(override.get("quality"), _safe_int(override.get("crf")))
    if quality is not None:
        quality = max(0, min(63, quality))

    preset = str(override.get("preset") or "").strip()
    scale_mode = _scale_mode(
        override.get("scale_mode", override.get("scale")),
        "original",
    )
    return {
        "codec": _codec_text(override.get("codec") or default_codec),
        "encoder": encoder,
        "quality": quality,
        "preset": preset,
        "scale_mode": scale_mode,
        "encoder_options": encoder_options,
    }


def _apply_profile_settings(result: dict[str, Any], profile: dict[str, Any]) -> None:
    options = _merge_encoder_options(result["encoder_options"], profile.get("encoder_options") or {})
    result["crf"] = profile.get("crf") if profile.get("crf") is not None else result["crf"]
    result["preset"] = profile.get("preset") or result["preset"]
    result["scale_mode"] = _scale_mode(profile.get("scale"), result["scale_mode"])
    result["encoder_options"] = options
    result["profile_key"] = profile.get("key") or ""
    result["profile_label"] = profile.get("label") or profile.get("key") or "Profil"


def _apply_manual_settings(result: dict[str, Any], manual: dict[str, Any]) -> None:
    encoder = manual["encoder"]
    options = _merge_encoder_options(result["encoder_options"], manual.get("encoder_options") or {}, encoder=encoder)
    options["encoder"] = encoder

    quality = manual.get("quality")
    if quality is not None:
        result["crf"] = quality
        quality_key = {"nvenc": "cq", "qsv": "q", "amf": "qp"}.get(encoder)
        if quality_key:
            options[quality_key] = quality

    preset = manual.get("preset") or ""
    if preset:
        result["preset"] = preset
        if encoder in {"nvenc", "qsv"}:
            options["preset"] = preset
        elif encoder == "amf":
            options["quality"] = preset

    result["scale_mode"] = manual.get("scale_mode") or result["scale_mode"]
    result["encoder_options"] = options
    result["profile_key"] = ""
    result["profile_label"] = f"Manuell ({encoder.upper()})"


def effective_encoder_settings(
    *,
    default_codec: str,
    default_crf: int,
    default_preset: str,
    default_scale_mode: str,
    default_encoder_options: dict[str, Any],
    file_override: dict[str, Any] | None,
) -> dict[str, Any]:
    """Berechnet die wirksamen Encoderwerte für eine Datei.

    Priorität: globale Werte < gespeichertes Encoder-Profil < manueller
    Encoder-Override der Datei. Ein manueller Override kann damit gezielt nur
    einzelne Dateien auf NVENC/CPU, andere Skalierung oder andere Qualität setzen.
    """
    result = {
        "codec": _codec_text(default_codec),
        "crf": default_crf,
        "preset": default_preset,
        "scale_mode": default_scale_mode,
        "encoder_options": deepcopy(default_encoder_options or {}),
        "profile_key": "",
        "profile_label": "",
    }
    override = file_override or {}
    profile = normalize_profile_override(
        override.get("encoder_profile"),
        default_codec=default_codec,
    )
    if profile is not None:
        _apply_profile_settings(result, profile)

    manual = normalize_encoder_override(
        override.get("encoder_override"),
        default_codec=default_codec,
    )
    if manual is not None:
        _apply_manual_settings(result, manual)

    sdr_hdr = override.get("sdr_hdr")
    if sdr_hdr is not None:
        result["encoder_options"]["sdr_hdr_enabled"] = _safe_bool(sdr_hdr, False)
    result["encoder_options"].update(runtime_encoder_capabilities(override))
    return result
