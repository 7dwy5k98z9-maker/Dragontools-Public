# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QDialog, QWidget

from ..core.settings import APP_NAME, APP_ORG, APP_VERSION
from .online_metadata_dialog_state import OnlineMetadataDialogStateMixin
from .online_metadata_dialog_view import OnlineMetadataDialogViewMixin
from .ui_helpers import install_persistent_window_geometry


class OnlineMetadataDialog(
    OnlineMetadataDialogStateMixin,
    OnlineMetadataDialogViewMixin,
    QDialog,
):
    """Settings facade for optional online metadata providers."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Online-Metadaten – Dragon Tools V{APP_VERSION}")
        self.setMinimumWidth(640)
        self.settings = QSettings(APP_ORG, APP_NAME)
        self._init_ui()
        self._load()
        install_persistent_window_geometry(self, "online_metadata_dialog", self.settings)
