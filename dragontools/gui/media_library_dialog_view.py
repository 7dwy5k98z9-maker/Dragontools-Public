# -*- coding: utf-8 -*-
"""Thin widget owner for the media-library dialog.

Each tab is built in a focused module.  This class owns the public widget
surface consumed by the existing controllers and coordinates tab construction.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QLabel,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .media_library_dialog_contracts import MediaLibraryDialogActions
from .media_library_dialog_options import (
    SEARCH_ITEM_TYPES,
    SEARCH_MODES,
    SEARCH_OPTIONS,
    SEARCH_SCOPES,
)
from .media_library_mapping_tab import build_mapping_tab
from .media_library_search_tab import build_search_tab, update_search_options
from .media_library_sql_tab import build_sql_tab
from .media_library_status_tab import build_status_tab

__all__ = [
    "MediaLibraryDialogActions",
    "MediaLibraryDialogView",
    "SEARCH_ITEM_TYPES",
    "SEARCH_MODES",
    "SEARCH_OPTIONS",
    "SEARCH_SCOPES",
]


class MediaLibraryDialogView:
    """Own the dialog widgets while delegating tab construction."""

    def __init__(self, dialog: QDialog, actions: MediaLibraryDialogActions) -> None:
        self.dialog = dialog
        self.actions = actions
        self.scan_sensitive_widgets: list[QWidget] = []
        self.nfo_scan_sensitive_widgets: list[QWidget] = []
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self.dialog)

        # Keep the introductory information visually grouped and make this
        # module itself the top-level widget/layout owner.
        intro_group = QGroupBox("Mediathek-Datenbank")
        intro_layout = QVBoxLayout(intro_group)
        intro = QLabel(
            "Dragon Tools speichert eine eigene SQLite-Mediathek. Jellyfin-Datenbanken werden nur gelesen "
            "und in eine DragonTools-Datenbank importiert; Jellyfin selbst wird niemals verändert."
        )
        intro.setWordWrap(True)
        intro_layout.addWidget(intro)
        root.addWidget(intro_group)

        self.tabs = QTabWidget()
        self.tabs.addTab(build_status_tab(self, self.actions), "Status / Import")
        self.tabs.addTab(build_mapping_tab(self, self.actions), "Pfad-Mapping")
        self.tabs.addTab(build_search_tab(self, self.actions), "Suchen")
        self.tabs.addTab(build_sql_tab(self, self.actions), "Bearbeiten")
        root.addWidget(self.tabs, 1)
        root.addWidget(self._build_dialog_buttons())

    def _build_dialog_buttons(self) -> QDialogButtonBox:
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close
        )
        save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        if save_button:
            save_button.setText("Speichern")
            save_button.clicked.connect(self.actions.save)
        close_button = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_button:
            close_button.setText("Schließen")
        buttons.rejected.connect(self.actions.save_and_close)
        return buttons

    def update_search_options(self, index: int | None = None) -> None:
        update_search_options(self, index)

    def set_scan_running(self, running: bool) -> None:
        for widget in self.scan_sensitive_widgets:
            widget.setEnabled(not running)
        self.scan_abort_btn.setEnabled(running)

    def set_nfo_scan_running(self, running: bool) -> None:
        for widget in self.nfo_scan_sensitive_widgets:
            widget.setEnabled(not running)
        self.nfo_abort_btn.setEnabled(running)
