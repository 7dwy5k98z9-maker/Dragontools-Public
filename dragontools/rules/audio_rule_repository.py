# -*- coding: utf-8 -*-
"""Loading and caching of audio rules."""
from __future__ import annotations

from typing import Any

from .audio_rule_basics import _DEFAULT_RULES
from .audio_rule_migration import migrate_audio_rules
from .rule_loader import load_named_rules

_rules_cache: dict[str, Any] | None = None

def _load_rules() -> dict[str, Any]:
    """Lädt Regeln aus ~/.../DragonTools/rules/audio_rules.json oder Default.

    Nutzt den zentralen Diagnosepfad aus ``rule_loader.load_named_rules``,
    damit fehlende/defekte Regeldateien dieselben sichtbaren Warnungen
    produzieren wie alle anderen Regel-Loader (Logfile + stderr).
    Die hart-kodierten ``_DEFAULT_RULES`` bleiben als letzter Fallback erhalten.
    """
    global _rules_cache
    if _rules_cache is not None:
        return _rules_cache

    _rules_cache = load_named_rules(
        "audio_rules",
        default=_DEFAULT_RULES,
        migrator=migrate_audio_rules,
    )
    return _rules_cache


def reload_rules() -> None:
    """Erzwingt Neu-Laden der Regeln (nach Speichern im Editor)."""
    global _rules_cache
    _rules_cache = None
