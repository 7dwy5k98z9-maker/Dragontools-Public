from __future__ import annotations

from enum import Enum

from .models import TargetCodec

_TARGET_CODEC_ALIASES = {
    "h264": TargetCodec.H264.value,
    "avc": TargetCodec.H264.value,
    "avc1": TargetCodec.H264.value,
    "x264": TargetCodec.H264.value,
    "h265": TargetCodec.H265.value,
    "hevc": TargetCodec.H265.value,
    "hvc1": TargetCodec.H265.value,
    "hev1": TargetCodec.H265.value,
    "x265": TargetCodec.H265.value,
    "av1": TargetCodec.AV1.value,
    "av01": TargetCodec.AV1.value,
}

SUPPORTED_TARGET_CODECS = frozenset(codec.value for codec in TargetCodec)


def _enum_or_value(value: object) -> object:
    """Return the serialized value for Enum-like objects without stringifying the Enum name."""
    if isinstance(value, Enum):
        return value.value
    enum_value = getattr(value, "value", None)
    return enum_value if enum_value is not None else value


def normalize_target_codec(value: object, *, strict: bool = True) -> str:
    """Normalize a configured target codec to ``h264``, ``h265`` or ``av1``.

    Target codecs are application configuration values, not free-form probe data.
    Unknown values therefore fail fast by default instead of silently selecting HEVC.
    """
    raw = _enum_or_value(value)
    text = str(raw or "").strip().lower()
    normalized = _TARGET_CODEC_ALIASES.get(text, text)
    if strict and normalized not in SUPPORTED_TARGET_CODECS:
        raise ValueError(
            f"Nicht unterstützter Ziel-Codec: {value!r}. "
            f"Erlaubt: {', '.join(sorted(SUPPORTED_TARGET_CODECS))}."
        )
    return normalized


def value_or_default(value, default):
    """Use a default only for ``None``; valid false-y values such as 0 stay intact."""
    return default if value is None else value
