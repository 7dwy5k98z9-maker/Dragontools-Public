# -*- coding: utf-8 -*-
"""Typed, defensive access helpers for QSettings-like objects."""
from __future__ import annotations

from typing import Any, Iterable

from .settings_app import APP_NAME, APP_ORG
from .type_utils import _safe_bool, _safe_float, _safe_int

SET_KEY_UI_SECTION_PREFIX = "ui/sections"


def ui_section_expanded_key(section_id: str) -> str:
    """Return the stable QSettings key for a collapsible UI section."""
    safe = str(section_id or "").strip().replace("\\", "/").strip("/")
    parts = [part.strip().replace(" ", "_") for part in safe.split("/") if part.strip()]
    name = "/".join(parts) or "default"
    return f"{SET_KEY_UI_SECTION_PREFIX}/{name}/expanded"


def app_qsettings():
    """Create the central QSettings instance lazily without a hard Qt dependency."""
    try:
        from PyQt6.QtCore import QSettings

        return QSettings(APP_ORG, APP_NAME)
    except Exception:
        return None


def settings_value(settings, key: str, default: Any = None, *, value_type=None) -> Any:
    """Read a QSettings-like value robustly and return ``default`` on access errors."""
    if settings is None:
        return default
    try:
        if value_type is not None:
            return settings.value(key, default, type=value_type)
        return settings.value(key, default)
    except TypeError:
        try:
            return settings.value(key, default)
        except Exception:
            return default
    except Exception:
        return default


def settings_bool(settings, key: str, default: bool) -> bool:
    return _safe_bool(settings_value(settings, key, default), default)


def settings_int(
    settings,
    key: str,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    value = settings_value(settings, key, default)
    number = _safe_int(value, int(default))
    if number is None:
        number = int(default)
    if minimum is not None:
        number = max(int(minimum), number)
    if maximum is not None:
        number = min(int(maximum), number)
    return number


def settings_float(
    settings,
    key: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    value = settings_value(settings, key, default)
    number = _safe_float(value, float(default))
    if minimum is not None:
        number = max(float(minimum), number)
    if maximum is not None:
        number = min(float(maximum), number)
    return number


def settings_text(
    settings,
    key: str,
    default: str = "",
    *,
    allowed: Iterable[str] | None = None,
) -> str:
    value = settings_value(settings, key, default, value_type=str)
    text = str(value or "").strip()
    if not text:
        text = str(default or "")
    if allowed is not None and text not in set(allowed):
        return str(default or "")
    return text


__all__ = [
    "SET_KEY_UI_SECTION_PREFIX",
    "ui_section_expanded_key",
    "app_qsettings",
    "settings_value",
    "settings_bool",
    "settings_int",
    "settings_float",
    "settings_text",
]
