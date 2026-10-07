# -*- coding: utf-8 -*-
"""Typed, defensive access helpers for QSettings-like objects."""
from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any, Iterable

from .settings_app import APP_NAME, APP_ORG
from .type_utils import _safe_bool, _safe_float, _safe_int

_LOG = logging.getLogger(__name__)


class SettingsSnapshot:
    """Read-only QSettings-compatible values, safe to pass into a worker."""

    def __init__(self, settings):
        self._values = {key: deepcopy(settings.value(key)) for key in settings.allKeys()}

    def value(self, key, default=None, *, type=None):
        value = deepcopy(self._values.get(key, default))
        if type is bool:
            return _safe_bool(value, bool(default))
        return type(value) if type is not None and value is not None else value

    def contains(self, key):
        return key in self._values

    def allKeys(self):
        return list(self._values)


def worker_settings_snapshot(settings=None):
    """Capture settings at the composition boundary, not in processing code."""
    source = settings if settings is not None else app_qsettings()
    if source is None:
        raise RuntimeError("Worker-Einstellungen konnten nicht geladen werden.")
    return SettingsSnapshot(source)


def raw_settings_snapshot(settings) -> dict[str, Any]:
    """Capture QSettings values exactly as stored, including DPAPI blobs.

    This snapshot is intended for transactional rollback.  It must not pass
    sensitive values through :func:`read_secret`, because an encrypted value
    can be temporarily undecryptable (different Windows account/machine,
    damaged user profile, etc.) while still being valuable data that must not
    be overwritten.
    """
    if settings is None:
        return {}
    return {
        str(key): deepcopy(settings.value(key))
        for key in settings.allKeys()
    }


def sync_settings_checked(settings) -> None:
    """Persist a QSettings-like store and fail on a reported storage error."""
    settings.sync()
    status_fn = getattr(settings, "status", None)
    if callable(status_fn):
        status = status_fn()
        if getattr(status, "value", status) != 0:
            raise OSError(f"Einstellungen konnten nicht gespeichert werden: {status}")


def restore_raw_settings_snapshot(
    settings,
    snapshot: dict[str, Any],
    *,
    sync: bool = True,
) -> None:
    """Restore an exact in-memory settings snapshot without secret re-encoding."""
    settings.clear()
    for key, value in snapshot.items():
        settings.setValue(str(key), deepcopy(value))
    if sync:
        sync_settings_checked(settings)


def save_settings_transaction(settings, writers: Iterable) -> bool:
    """Run settings writers transactionally.

    Writers are callables returning ``False`` for validation failure and any
    other value for success.  If a later section rejects the save, or if a
    writer/sync raises, every QSettings value is restored to the exact raw
    state from before the first writer.  This prevents the Settings dialog
    from partially committing earlier sections when a later section fails.
    """
    snapshot = raw_settings_snapshot(settings)
    try:
        for writer in writers:
            if writer() is False:
                restore_raw_settings_snapshot(settings, snapshot)
                return False
        sync_settings_checked(settings)
        return True
    except Exception:
        try:
            restore_raw_settings_snapshot(settings, snapshot)
        except Exception:
            _LOG.exception("QSettings-Rollback nach fehlgeschlagenem Speichern ist fehlgeschlagen.")
        raise

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
        _LOG.debug("Zentrale QSettings-Instanz konnte nicht erstellt werden.", exc_info=True)
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
            _LOG.debug("QSettings-Wert konnte nicht gelesen werden: %s", key, exc_info=True)
            return default
    except Exception:
        _LOG.debug("QSettings-Wert konnte nicht gelesen werden: %s", key, exc_info=True)
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
    "SettingsSnapshot",
    "worker_settings_snapshot",
    "raw_settings_snapshot",
    "sync_settings_checked",
    "restore_raw_settings_snapshot",
    "save_settings_transaction",
    "settings_value",
    "settings_bool",
    "settings_int",
    "settings_float",
    "settings_text",
]
