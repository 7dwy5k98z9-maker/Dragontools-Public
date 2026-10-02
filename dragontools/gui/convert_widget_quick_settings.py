# -*- coding: utf-8 -*-
"""Persisted quick toggles shown next to the converter queue controls."""
from __future__ import annotations

from dataclasses import dataclass

from ..core.settings_access import settings_bool
from ..core.settings_conversion import (
    DEFAULT_HDR10PLUS_GENERATOR_ENABLED,
    DEFAULT_QUALITY_TARGET_ENABLED,
    DEFAULT_SDR_HDR_ENABLED,
    SET_KEY_HDR10PLUS_GENERATOR_ENABLED,
    SET_KEY_QUALITY_TARGET_ENABLED,
    SET_KEY_SDR_HDR_ENABLED,
)
from ..core.settings_watch import DEFAULT_WATCH_ENABLED, SET_KEY_WATCH_ENABLED
from ..core.settings_postprocess import (
    DEFAULT_NFO_ENABLED, DEFAULT_TRICKPLAY_ENABLED,
    SET_KEY_NFO_ENABLED, SET_KEY_TRICKPLAY_ENABLED,
)


@dataclass(frozen=True)
class QuickToggleSpec:
    attr_name: str
    label: str
    key: str
    default: bool
    tooltip: str
    subtitle_rule: bool = False
    rule_group: str | None = None


QUICK_TOGGLE_SPECS = (
    QuickToggleSpec(
        "forced_burn_quick_cb", "Forced einbrennen", "auto_burn_forced", True,
        "Forced-Untertitel gemäß Untertitelregeln automatisch einbrennen. "
        "Manuelle Dateivorgaben bleiben wirksam. Gilt für neu gestartete Jobs.",
        subtitle_rule=True, rule_group="burn_in_rules",
    ),
    QuickToggleSpec(
        "subtitle_external_quick_cb", "Untertitel extern", "additional_sidecars_enabled", False,
        "Ausgewählte Untertitel zusätzlich im ursprünglichen Format neben der Ausgabe speichern. "
        "Die MP4-Untertitelablage folgt weiterhin den MP4-Regeln. Gilt für neu gestartete Jobs.",
        subtitle_rule=True,
    ),
    QuickToggleSpec(
        "pgs_to_srt_quick_cb", "PGS → SRT", "pgs_to_srt_enabled", False,
        "Ausgewählte PGS/SUP-Spuren zusätzlich per OCR als SRT exportieren. "
        "Benötigt FFmpeg und Tesseract; Original-PGS bleibt erhalten. Wirkt auf neue Jobs.", True,
    ),
    QuickToggleSpec(
        "text_to_srt_quick_cb", "Text → SRT", "text_to_srt_sidecar_enabled", False,
        "Ausgewählte Textuntertitel zusätzlich als SRT neben der Ausgabe speichern. Wirkt auf neue Jobs.", True,
    ),
    QuickToggleSpec(
        "quality_target_quick_cb", "Auto-Qualität", SET_KEY_QUALITY_TARGET_ENABLED,
        DEFAULT_QUALITY_TARGET_ENABLED,
        "Qualitätswert für geeignete SDR-Videos automatisch anhand des eingestellten VMAF-Ziels bestimmen. "
        "Zusätzliche Testdurchläufe benötigen Zeit. HDR/DV/HLG verwendet den festen Qualitätswert. "
        "Gilt für neu gestartete Jobs.",
    ),
    QuickToggleSpec(
        "hdr10plus_generator_quick_cb",
        "HDR+ Generator",
        SET_KEY_HDR10PLUS_GENERATOR_ENABLED,
        DEFAULT_HDR10PLUS_GENERATOR_ENABLED,
        "HDR10+-Generator global ein-/ausschalten. Wirkt auf neu gestartete Jobs.",
    ),
    QuickToggleSpec(
        "sdr_hdr_quick_cb",
        "SDR → HDR",
        SET_KEY_SDR_HDR_ENABLED,
        DEFAULT_SDR_HDR_ENABLED,
        "SDR→HDR Enhancement global ein-/ausschalten. Wirkt auf neu gestartete Jobs.",
    ),
    QuickToggleSpec(
        "nfo_quick_cb", "NFO", SET_KEY_NFO_ENABLED, DEFAULT_NFO_ENABLED,
        "Jellyfin-NFO nach erfolgreicher Konvertierung erstellen. Gilt für neu gestartete Jobs.",
    ),
    QuickToggleSpec(
        "trickplay_quick_cb", "Trickplay", SET_KEY_TRICKPLAY_ENABLED, DEFAULT_TRICKPLAY_ENABLED,
        "Jellyfin-Vorschaubilder zum Spulen erzeugen. Benötigt zusätzliche Rechenzeit. "
        "Gilt für neu gestartete Jobs.",
    ),
    QuickToggleSpec(
        "watch_folder_quick_cb",
        "Watch-Folder",
        SET_KEY_WATCH_ENABLED,
        DEFAULT_WATCH_ENABLED,
        "Watch-Folder-Automatisierung global ein-/ausschalten.",
    ),
)


def quick_toggle_value(settings, spec: QuickToggleSpec) -> bool:
    if spec.subtitle_rule:
        from ..core.type_utils import _safe_bool
        from .rules_dialog_storage import _load
        rules = _load("subtitle_rules")
        if spec.rule_group:
            rules = rules.get(spec.rule_group, {})
        return _safe_bool(rules.get(spec.key), spec.default)
    return settings_bool(settings, spec.key, spec.default)


def set_quick_toggle_value(settings, spec: QuickToggleSpec, enabled: bool) -> None:
    if spec.subtitle_rule:
        from .rules_dialog_storage import _load, _save
        rules = _load("subtitle_rules")
        if spec.rule_group:
            group = dict(rules.get(spec.rule_group, {}))
            group[spec.key] = bool(enabled)
            rules[spec.rule_group] = group
        else:
            rules[spec.key] = bool(enabled)
        _save("subtitle_rules", rules)
        return
    settings.setValue(spec.key, bool(enabled))
    sync = getattr(settings, "sync", None)
    if callable(sync):
        sync()


__all__ = ["QuickToggleSpec", "QUICK_TOGGLE_SPECS", "quick_toggle_value", "set_quick_toggle_value"]
