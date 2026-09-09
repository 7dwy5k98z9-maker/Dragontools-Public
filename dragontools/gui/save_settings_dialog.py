# -*- coding: utf-8 -*-
from __future__ import annotations

from ..core.settings import APP_VERSION
from .settings_dialog import SettingsDialog


class SaveSettingsDialog(SettingsDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(
            parent,
            visible_sections=("save",),
            window_title=f"Speichereinstellungen - Dragon Tools V{APP_VERSION}",
        )
