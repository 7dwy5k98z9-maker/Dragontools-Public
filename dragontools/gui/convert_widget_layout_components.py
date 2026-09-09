# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QPixmap, QColor
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSpinBox, QFrame, QSizePolicy, QTextEdit, QVBoxLayout, QWidget,
    QGridLayout, QToolButton,
)
from ..core.settings import SET_KEY_AUTOCROP_ENABLED, SET_KEY_IMAX_DETECT, settings_bool, settings_value, ui_section_expanded_key
from .convert_widget_custom_widgets import BannerLabel, DragonProgressBar, _find_banner_single
from .convert_widget_file_queue import FileListWidget
from .info_button import InfoButton

class CollapsibleGroupBox(QWidget):
    """
    Schlanker einklappbarer Bereich für PyQt6.

    Vorteil gegenüber einer checkable QGroupBox:
    - kein störendes Checkbox-Layout im Titel
    - sauberer Pfeil-Indikator
    - Inhalt wird wirklich ausgeblendet und spart vertikal Platz
    """

    def __init__(
        self,
        title: str,
        *,
        collapsed: bool = False,
        parent: QWidget | None = None,
        settings: QSettings | None = None,
        section_id: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._title = title
        self._settings = settings
        self._settings_key = ui_section_expanded_key(section_id) if section_id else None
        expanded = not collapsed
        if self._settings_key:
            expanded = settings_bool(self._settings, self._settings_key, expanded)

        self.toggle_btn = QToolButton()
        self.toggle_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(expanded)
        self.toggle_btn.setAutoRaise(True)
        self.toggle_btn.toggled.connect(self._apply_state)
        self.toggle_btn.clicked.connect(self._save_user_state)

        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(8, 6, 8, 8)
        self.content_layout.setSpacing(5)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.toggle_btn)
        root.addWidget(self.content)

        self.setStyleSheet("""
            CollapsibleGroupBox {
                border: 1px solid #444;
                border-radius: 4px;
                margin-top: 4px;
            }
            QToolButton {
                font-weight: bold;
                padding: 5px 8px;
                text-align: left;
            }
        """)
        self._apply_state()

    def addLayout(self, layout: QGridLayout | QVBoxLayout | QHBoxLayout) -> None:
        self.content_layout.addLayout(layout)

    def addWidget(self, widget: QWidget) -> None:
        self.content_layout.addWidget(widget)

    def setCollapsed(self, collapsed: bool) -> None:
        self.toggle_btn.setChecked(not collapsed)
        self._apply_state()

    def hasPersistedState(self) -> bool:
        if not self._settings or not self._settings_key:
            return False
        try:
            return bool(self._settings.contains(self._settings_key))
        except Exception:
            return settings_value(self._settings, self._settings_key, None) is not None

    def _save_user_state(self, _checked: bool | None = None) -> None:
        if not self._settings or not self._settings_key:
            return
        try:
            self._settings.setValue(self._settings_key, self.toggle_btn.isChecked())
            self._settings.sync()
        except Exception:
            return

    def _apply_state(self, _checked: bool | None = None) -> None:
        expanded = self.toggle_btn.isChecked()
        self.content.setVisible(expanded)
        arrow = "▼" if expanded else "▶"
        self.toggle_btn.setText(f"{arrow} {self._title}")

class FileListBannerOverlay(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.file_list = FileListWidget()
        self.file_list.setMinimumHeight(350)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.file_list)

@dataclass
class ConvertWidgetUI:
    """
    Lightweight-Datenklasse mit direkten Referenzen auf alle relevanten
    UI-Widgets von ConvertWidget.

    Wird nach ConvertWidgetLayoutBuilder.build() instanziiert und per
    Dependency Injection an ConversionController, ConversionResultService
    und MovePreflightController übergeben.  Kein QObject, keine Signale.
    """
    # Fortschritts-Widgets
    file_lbl: object          # QLabel
    file_focus_combo: object  # QComboBox
    file_bar: object          # DragonProgressBar
    eta_lbl: object           # QLabel
    total_lbl: object         # QLabel
    progress_bar: object      # DragonProgressBar
    # Steuerungs-Buttons
    start_btn: object         # QPushButton
    dv_remux_btn: object      # QPushButton
    move_only_btn: object     # QPushButton
    move_finished_btn: object # QPushButton
    pause_btn: object         # QPushButton
    abort_btn: object         # QPushButton
    abort_combo: object       # QComboBox
    curlog_btn: object        # QPushButton
    # Datei-Liste
    file_list: object         # FileListWidget
    # Options-Checkboxen
    over_cb: object           # QCheckBox
    strip_cb: object          # QCheckBox
    move_cb: object           # QCheckBox
    shut_cb: object           # QCheckBox
    # Encoder-Controls (hidden, aber referenziert)
    crf_spin: object          # QSpinBox
    preset_combo: object      # QComboBox
    scale_combo: object       # QComboBox
