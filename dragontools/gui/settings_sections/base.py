# -*- coding: utf-8 -*-
"""Gemeinsame Infrastruktur für SettingsDialog-Teilbereiche."""
from __future__ import annotations

from typing import TYPE_CHECKING
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QVBoxLayout

if TYPE_CHECKING:
    from ..settings_dialog import SettingsDialog


class SettingsSection:
    """Kleine, testbare Verantwortungseinheit des Einstellungsdialogs."""

    section_keys: tuple[str, ...] = ()

    def __init__(self, dialog: "SettingsDialog") -> None:
        self.dialog = dialog
        self.settings: QSettings = dialog.settings

    def build(self, layout: QVBoxLayout) -> None:
        raise NotImplementedError

    def load(self) -> None:
        pass

    def save(self) -> bool:
        return True

    def is_visible(self, section_key: str) -> bool:
        """Keep writes inside the UI area the user actually opened."""
        return section_key in getattr(self.dialog, "_visible_sections", self.section_keys)
