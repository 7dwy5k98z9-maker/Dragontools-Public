# -*- coding: utf-8 -*-
"""Globaler Settings-Dialog als schlanke Orchestrierungs-Fassade."""
from __future__ import annotations

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QGridLayout, QLabel, QLineEdit,
    QScrollArea, QVBoxLayout, QWidget,
)

from ..core.audit_log import log_qsettings_changes, snapshot_qsettings
from ..core.settings import APP_NAME, APP_ORG, APP_VERSION
from .info_button import InfoButton
from .settings_sections import (
    MediaPostprocessSection, RuntimeToolsSection, SafetyValidationSection,
    StorageLoggingSection, VideoAnalysisSection,
)
from .ui_helpers import install_persistent_window_geometry


class SettingsDialog(QDialog):
    SECTION_TITLES = {
        "paths": "Speicherpfade festlegen",
        "logging": "Loggingordner festlegen",
        "log_cleanup": "Log-Bereinigung",
        "tools": "Werkzeugpfade definieren",
        "defaults": "Standardwerte",
        "parallel": "Parallele Bearbeitung",
        "media_library": "Mediathek-Datenbank",
        "postprocess": "Jellyfin NFO / Trickplay",
        "source_visual": "Quellbildprüfung",
        "containers": "Ausgabecontainer",
        "autocrop": "Auto-Crop",
        "imax": "IMAX Auto-Erkennung",
        "save": "Speichereinstellungen",
        "validation": "Output-Validierung / Reparatur",
        "move_conflict": "Verschieben – Konfliktverhalten",
        "timeouts": "Timeouts",
    }

    def __init__(self, parent=None, *, visible_sections: tuple[str, ...] | None = None, window_title: str | None = None):
        super().__init__(parent)
        self._visible_sections = tuple(
            section for section in (visible_sections or self.SECTION_TITLES.keys())
            if section in self.SECTION_TITLES
        )
        self._section_widgets: dict[str, QWidget] = {}
        self.setWindowTitle(window_title or f"Einstellungen – Dragon Tools V{APP_VERSION}")
        self.setMinimumWidth(680)
        self.settings = QSettings(APP_ORG, APP_NAME)

        self._storage_section = StorageLoggingSection(self)
        self._runtime_section = RuntimeToolsSection(self)
        self._media_section = MediaPostprocessSection(self)
        self._video_section = VideoAnalysisSection(self)
        self._safety_section = SafetyValidationSection(self)
        self._sections = (
            self._storage_section, self._runtime_section, self._media_section,
            self._video_section, self._safety_section,
        )

        self._init_ui()
        self._apply_section_visibility()
        self._load()
        geometry_scope = "all" if len(self._visible_sections) != 1 else self._visible_sections[0]
        install_persistent_window_geometry(self, f"settings_dialog/{geometry_scope}", self.settings)

    def _ib(self, text: str) -> InfoButton:
        return InfoButton(text)

    def row(self, grid: QGridLayout, row: int, label: str, widget: QWidget, info: str, browse_fn=None) -> None:
        grid.addWidget(QLabel(label), row, 0)
        grid.addWidget(widget, row, 1)
        col = 2
        if browse_fn:
            from PyQt6.QtWidgets import QPushButton
            btn = QPushButton("…")
            btn.setFixedWidth(28)
            btn.clicked.connect(browse_fn)
            grid.addWidget(btn, row, col)
            col += 1
        grid.addWidget(self._ib(info), row, col)

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        for section in self._sections:
            section.build(layout)
        scroll.setWidget(inner)
        root.addWidget(scroll)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    def _apply_section_visibility(self) -> None:
        visible = set(self._visible_sections) or set(self.SECTION_TITLES)
        for key, widget in self._section_widgets.items():
            widget.setVisible(key in visible)
        if len(visible) == 1:
            only = next(iter(visible))
            self.setWindowTitle(f"{self.SECTION_TITLES[only]} – Dragon Tools V{APP_VERSION}")

    def browse(self, edit: QLineEdit) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Ordner wählen", edit.text())
        if directory:
            edit.setText(directory)

    def _load(self) -> None:
        for section in self._sections:
            section.load()

    def _save(self) -> None:
        before_settings = snapshot_qsettings(self.settings)
        for section in self._sections:
            if not section.save():
                return
        try:
            log_qsettings_changes(
                "Globale Einstellungen gespeichert",
                before_settings,
                snapshot_qsettings(self.settings),
                settings=self.settings,
            )
        except Exception:
            # Audit-Logging ist best effort und darf das Speichern der Einstellungen nicht verhindern.
            pass
        self.accept()

    # Öffentliche Callback-Grenze für die fokussierten Settings-Sections.
    def browse_media_library_db(self) -> None:
        self._media_section.browse_database()

    def open_media_library_dialog(self) -> None:
        self._media_section.open_media_library_dialog()

    def open_timeout_settings(self) -> None:
        self._safety_section.open_timeout_settings()

    def sync_autocrop_mode(self) -> None:
        self._video_section.sync_autocrop_mode()

    def cleanup_logs(self, *, all_logs: bool) -> None:
        self._storage_section.cleanup_logs(all_logs=all_logs)

    def auto_detect(self, tool: str, edit: QLineEdit) -> None:
        self._runtime_section.auto_detect(tool, edit)

    def auto_detect_all(self) -> None:
        self._runtime_section.auto_detect_all()
