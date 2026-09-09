# -*- coding: utf-8 -*-
"""
dragontools/gui/ui_helpers.py

Gemeinsame UI-Hilfsfunktionen, die von mehreren GUI-Klassen benötigt werden.
Freie Funktionen statt Methoden – kein Widget-Owner-Zugriff nötig.
"""
from __future__ import annotations

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import QListWidget, QWidget

from ..core.settings import APP_NAME, APP_ORG


def set_file_list_item_text(file_list: QListWidget, path: str, text: str) -> None:
    """Setzt den Anzeigetext des List-Items, dessen UserRole == path ist.

    Früher als private Methode in ConvertWidget, ConversionController und
    ConversionResultService dreifach dupliziert.  Jetzt eine einzige
    kanonische Implementierung.
    """
    if hasattr(file_list, "item_for_path"):
        item = file_list.item_for_path(path)
        if item is not None:
            item.setText(text)
            return

    for i in range(file_list.count()):
        item = file_list.item(i)
        if item and item.data(Qt.ItemDataRole.UserRole) == path:
            item.setText(text)
            return


def window_geometry_key(window_id: str) -> str:
    """Stable QSettings key for persisted dialog/window geometry."""
    safe = str(window_id or "").strip().replace("\\", "/").strip("/")
    parts = [part.strip().replace(" ", "_") for part in safe.split("/") if part.strip()]
    name = "/".join(parts) if parts else "default"
    return f"windows/{name}/geometry"


def restore_window_geometry(
    widget: QWidget,
    window_id: str,
    settings: QSettings | None = None,
) -> None:
    """Restore a widget geometry if it was saved before."""
    active_settings = settings or QSettings(APP_ORG, APP_NAME)
    try:
        geometry = active_settings.value(window_geometry_key(window_id))
        if geometry:
            widget.restoreGeometry(geometry)
    except Exception:
        return


def save_window_geometry(
    widget: QWidget,
    window_id: str,
    settings: QSettings | None = None,
) -> None:
    """Persist current widget geometry without disturbing the close flow."""
    active_settings = settings or QSettings(APP_ORG, APP_NAME)
    try:
        active_settings.setValue(window_geometry_key(window_id), widget.saveGeometry())
        active_settings.sync()
    except Exception:
        return


def install_persistent_window_geometry(
    widget: QWidget,
    window_id: str,
    settings: QSettings | None = None,
) -> None:
    """Restore immediately and save again when a QDialog finishes."""
    restore_window_geometry(widget, window_id, settings)
    finished = getattr(widget, "finished", None)
    if finished is None:
        return
    try:
        finished.connect(
            lambda _result=0, w=widget, wid=window_id, s=settings: save_window_geometry(w, wid, s)
        )
    except Exception:
        return
