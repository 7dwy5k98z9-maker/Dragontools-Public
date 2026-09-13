# -*- coding: utf-8 -*-
from __future__ import annotations

from ..core.encoder_profile_override import (
    MODE_TO_SCALE_LABEL,
    SCALE_LABELS_TO_MODE,
    normalize_encoder_override,
)

_ENCODER_KEYS = {"cpu", "nvenc", "qsv", "amf"}
_ENCODER_OPTION_KEYS = {
    "cpu": {"tune", "aq_mode", "aq_strength", "psy_rd", "psy_rdoq", "bf", "rc_lookahead"},
    "nvenc": {
        "preset", "cq", "bf", "bref_mode", "rc_lookahead", "lookahead_level",
        "multipass", "aq_strength", "spatial_aq", "temporal_aq",
    },
    "qsv": {"preset", "q", "lookahead_depth"},
    "amf": {"quality", "qp"},
}


def default_encoder_preset(encoder: str, default_codec: str) -> str:
    return {
        "cpu": "6" if default_codec == "av1" else "medium",
        "nvenc": "p6",
        "qsv": "medium",
        "amf": "balanced",
    }[encoder]


def encoder_override_summary(raw: dict | None, default_codec: str) -> str:
    value = normalize_encoder_override(raw, default_codec=default_codec)
    if not value:
        return "Global / Profil"
    encoder_key = value["encoder"]
    quality_label = {"cpu": "CRF", "nvenc": "CQ", "qsv": "Q", "amf": "QP"}[encoder_key]
    quality = value.get("quality")
    scale_mode = value.get("scale_mode") or "original"
    scale = MODE_TO_SCALE_LABEL.get(scale_mode, scale_mode)
    preset = value.get("preset") or "-"
    return f"{encoder_key.upper()} {quality_label} {quality if quality is not None else '-'} | {preset} | {scale}"


def global_encoder_snapshot(owner) -> dict:
    options = dict(owner._enc_settings.collect_enc_opts() or {})
    encoder = str(options.get("encoder") or "cpu").lower()
    if encoder not in _ENCODER_KEYS:
        encoder = "cpu"

    default_quality = getattr(owner, "crf_spin").value()
    quality = {
        "cpu": default_quality,
        "nvenc": options.get("cq", default_quality),
        "qsv": options.get("q", default_quality),
        "amf": options.get("qp", default_quality),
    }[encoder]
    preset = {
        "cpu": getattr(owner, "preset_combo").currentText(),
        "nvenc": options.get("preset", "p6"),
        "qsv": options.get("preset", "medium"),
        "amf": options.get("quality", "balanced"),
    }[encoder]
    filtered = {key: options[key] for key in _ENCODER_OPTION_KEYS[encoder] if key in options}
    filtered["encoder"] = encoder
    scale_text = str(owner.scale_combo.currentText() or "original")

    return {
        "codec": owner.default_codec,
        "encoder": encoder,
        "quality": int(quality),
        "preset": str(preset),
        "scale_mode": SCALE_LABELS_TO_MODE.get(scale_text, "original"),
        "encoder_options": filtered,
    }


def common_encoder_override(owner, paths: list[str]) -> dict:
    values = [
        dict(owner._state.file_overrides.get(path) or {}).get("encoder_override")
        for path in paths
    ]
    first = values[0] if values else None
    if first is not None and all(value == first for value in values[1:]):
        return {"encoder_override": dict(first)}
    return {}
