# -*- coding: utf-8 -*-
"""
Gemeinsame, zustandslose Typkonvertierungs-Hilfsfunktionen für DragonTools.

Kein Import von PyQt6, kein Import aus anderen dragontools-Modulen –
diese Datei darf von überall im Paket importiert werden, ohne
Zirkularitäts- oder Abhängigkeitsprobleme zu verursachen.

Persistierte Werte kommen je nach Quelle als echte JSON-Typen, QSettings-
Strings oder Legacy-Werte wie ``"23.0"``/``"false"`` an. Diese Helfer sind
die kanonische Normalisierungsschicht dafür.
"""
from __future__ import annotations

from typing import Any

_TRUE_STRINGS = {"1", "true", "yes", "on", "ja", "y"}
_FALSE_STRINGS = {"0", "false", "no", "off", "nein", "n", ""}
_NULL_STRINGS = {"n/a", "none", "null"}


def _safe_int(value: Any, default: int | None = None) -> int | None:
    """Konvertiert *value* sicher nach ``int``.

    Unterstützt auch Legacy-Strings wie ``"23.0"`` und ``"23,0"``.
    Bei ``None``, leeren/Null-Strings oder ungültigen Werten wird *default*
    zurückgegeben.
    """
    if value is None:
        return default
    if isinstance(value, str):
        text = value.strip()
        if text.lower() in _NULL_STRINGS or text == "":
            return default
        value = text.replace(",", ".")
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        try:
            return int(float(value))
        except (TypeError, ValueError, OverflowError):
            return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Konvertiert *value* sicher nach ``float`` inklusive Dezimalkomma."""
    if value is None:
        return default
    if isinstance(value, str):
        text = value.strip()
        if text.lower() in _NULL_STRINGS or text == "":
            return default
        value = text.replace(",", ".")
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _safe_bool(value: Any, default: bool = False) -> bool:
    """Konvertiert persistierte Bool-Werte ohne Python-String-Falle.

    ``bool("false")`` ist in Python ``True`` und damit für JSON/QSettings-
    Legacywerte ungeeignet. Bekannte True-/False-Strings sowie numerische
    Werte werden explizit interpretiert; unbekannte Strings fallen auf
    *default* zurück statt still als ``True`` zu gelten.
    """
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if text in _TRUE_STRINGS:
        return True
    if text in _FALSE_STRINGS or text in _NULL_STRINGS:
        return False if text in _FALSE_STRINGS else bool(default)
    return bool(default)
