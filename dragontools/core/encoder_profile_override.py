from __future__ import annotations

from typing import Any

from .type_utils import _safe_int


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
    options = dict(result["encoder_options"])
    options.update(profile.get("encoder_options") or {})
    result["crf"] = profile.get("crf") if profile.get("crf") is not None else result["crf"]
    result["preset"] = profile.get("preset") or result["preset"]
    result["scale_mode"] = _scale_mode(profile.get("scale"), result["scale_mode"])
    result["encoder_options"] = options
    result["profile_key"] = profile.get("key") or ""
    result["profile_label"] = profile.get("label") or profile.get("key") or "Profil"


def _apply_manual_settings(result: dict[str, Any], manual: dict[str, Any]) -> None:
    options = dict(result["encoder_options"])
    options.update(manual.get("encoder_options") or {})
    encoder = manual["encoder"]
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
        "encoder_options": dict(default_encoder_options or {}),
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
    return result
