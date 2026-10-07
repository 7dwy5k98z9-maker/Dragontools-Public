# -*- coding: utf-8 -*-
"""Mehrfachauswahl fuer bestehende Serienordner im Preflight."""
from __future__ import annotations

from PyQt6.QtWidgets import QComboBox, QVBoxLayout

from ..core.path_syntax import user_path_name
from .preflight_widget_common import _series_root_from_input, current_series_base

NO_SERIES_FOLDER_CHOICE = object()


def install_series_folder_choice(widget, layout: QVBoxLayout) -> None:
    combo = QComboBox()
    combo.setVisible(False)
    combo.currentIndexChanged.connect(lambda _idx=0: getattr(widget, "_update_preview")())
    widget._folder_choice_combo = combo
    layout.addWidget(combo)


def hide_series_folder_choices(widget) -> None:
    combo = widget.__dict__.get("_folder_choice_combo")
    if combo is not None:
        combo.setVisible(False)


def series_folder_choices_active(widget) -> bool:
    """A hidden parent does not revoke the user's explicit folder selection."""
    combo = widget.__dict__.get("_folder_choice_combo")
    if combo is None:
        return False
    hidden = getattr(combo, "isHidden", None)
    return not hidden() if callable(hidden) else bool(combo.isVisible())


def selected_series_folder_choice(widget, base: str, series_name: str):
    combo = widget.__dict__.get("_folder_choice_combo")
    if not series_folder_choices_active(widget):
        return NO_SERIES_FOLDER_CHOICE
    context = widget.__dict__.get("_folder_choice_context")
    if context is not None and context != (base, series_name):
        hide_series_folder_choices(widget)
        return NO_SERIES_FOLDER_CHOICE
    data = combo.currentData()
    if data == "__new__":
        return _series_root_from_input(base, series_name)
    return str(data or "")


def show_series_folder_choices(
    widget,
    *,
    choices: list[dict],
    series_name: str,
    suggested_series_name: str = "",
) -> None:
    if widget._series_edit.text().strip() != series_name:
        return
    suggestion = str(suggested_series_name or "").strip()
    if suggestion and widget._series_edit.text().strip() == series_name:
        widget._series_edit.setText(suggestion)
    combo = widget.__dict__.get("_folder_choice_combo")
    if combo is None:
        return
    widget._resolved_series_key = None
    widget._resolved_series_dir = None
    combo.blockSignals(True)
    combo.clear()
    combo.addItem("Bitte Serienordner wählen", "")
    for choice in choices:
        path = str(choice.get("path") or "")
        label = f"{choice.get('base_type') or 'Ordner'}: {user_path_name(path)}"
        combo.addItem(label, path)
    combo.addItem("Neuen Ordner aus Serienfeld verwenden", "__new__")
    combo.setCurrentIndex(0)
    combo.blockSignals(False)
    combo.setVisible(True)
    widget._folder_choice_context = (current_series_base(widget), widget._series_edit.text().strip())
    widget._metadata_hint.setText("  ⚠️ Mehrere passende Serienordner gefunden – bitte Zielordner auswählen.")
    widget._metadata_hint.setStyleSheet("color:#b45309; font-size:11px;")
    widget._metadata_hint.setVisible(True)
    getattr(widget, "_update_preview")()


def validate_series_folder_choice(widget) -> tuple[bool, str]:
    combo = widget.__dict__.get("_folder_choice_combo")
    if series_folder_choices_active(widget) and not combo.currentData():
        return False, "Bitte wähle den passenden Serienordner oder 'Neuen Ordner'."
    return True, ""
