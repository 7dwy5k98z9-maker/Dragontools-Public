# -*- coding: utf-8 -*-
"""
dragontools/gui/timeout_settings_dialog.py

Dialog zur individuellen Konfiguration aller Prozess-Timeouts.

Zeitangaben werden in Minuten angezeigt und eingegeben;
intern wird in Sekunden gespeichert.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QSpinBox, QPushButton,
    QDialogButtonBox, QScrollArea, QWidget, QFrame,
    QSizePolicy, QMessageBox, QCheckBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from ..core.timeout_settings import (
    TIMEOUT_DEFS, TimeoutDef,
    get_timeout_value, is_timeout_enabled, save_all_timeouts,
)
from .info_button import InfoButton
from .ui_helpers import install_persistent_window_geometry


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _s_to_min(seconds: int) -> int:
    """Sekunden → ganze Minuten (aufgerundet auf 1 Minute mindestens)."""
    return max(1, round(seconds / 60))


def _min_to_s(minutes: int) -> int:
    """Minuten → Sekunden."""
    return minutes * 60


def _format_default(seconds: int) -> str:
    """Lesbare Standardwert-Anzeige, z.B. '240 Min (4 Std)'."""
    mins = _s_to_min(seconds)
    if mins >= 60 and mins % 60 == 0:
        return f"{mins} Min ({mins // 60} Std)"
    elif mins >= 60:
        h = mins // 60
        m = mins % 60
        return f"{mins} Min ({h} Std {m} Min)"
    return f"{mins} Min"


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

class TimeoutSettingsDialog(QDialog):
    """Dialog zur Konfiguration aller Prozess-Timeouts in Minuten."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⏱ Timeout-Einstellungen – Dragon Tools")
        self.setMinimumWidth(660)
        self.setMinimumHeight(520)
        self.resize(700, 620)

        # key → Widget-Mapping (für Load/Save)
        self._spinboxes: dict[str, QSpinBox] = {}
        self._enabled_cbs: dict[str, QCheckBox] = {}

        self._init_ui()
        self._load()
        install_persistent_window_geometry(self, "timeout_settings_dialog")

    # ── UI-Aufbau ────────────────────────────────────────────────────────────

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(8)

        # Kopfzeile
        header = QLabel(
            "Hier kannst du für jeden Prozessschritt individuell festlegen, "
            "wie lange er maximal laufen darf, bevor er automatisch abgebrochen wird.\n"
            "Alle Zeitangaben sind in <b>Minuten</b>. "
            "Deaktivierte Timeouts bleiben gespeichert, werden aber nicht angewendet. "
            "Klicke auf <b>ℹ️</b> für eine Erklärung des jeweiligen Timeouts."
        )
        header.setWordWrap(True)
        header.setContentsMargins(4, 4, 4, 8)
        root.addWidget(header)

        # Trennlinie
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(line)

        # Scrollbereich
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(14)
        content_layout.setContentsMargins(4, 4, 8, 4)

        # Gruppen aufbauen
        categories: dict[str, list[TimeoutDef]] = {}
        for td in TIMEOUT_DEFS:
            categories.setdefault(td.category, []).append(td)

        category_icons = {
            "DV-Pipeline": "🎬",
            "Encoder":     "⚙️",
            "Untertitel":  "💬",
            "Analyse":     "🔍",
        }

        for cat_name, entries in categories.items():
            icon = category_icons.get(cat_name, "⏱")
            grp = self._build_group(f"{icon}  {cat_name}", entries)
            content_layout.addWidget(grp)

        content_layout.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        # Trennlinie vor Buttons
        line2 = QFrame()
        line2.setFrameShape(QFrame.Shape.HLine)
        line2.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(line2)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 4, 0, 0)

        reset_all_btn = QPushButton("🔄 Alle auf Standard zurücksetzen")
        reset_all_btn.setToolTip("Setzt alle Timeouts auf ihre werksseitigen Standardwerte zurück.")
        reset_all_btn.clicked.connect(self._reset_all)
        btn_row.addWidget(reset_all_btn)

        btn_row.addStretch()

        bbox = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bbox.accepted.connect(self._save_and_accept)
        bbox.rejected.connect(self.reject)
        btn_row.addWidget(bbox)

        root.addLayout(btn_row)

    def _build_group(self, title: str, entries: list[TimeoutDef]) -> QGroupBox:
        """Baut eine QGroupBox mit Grid-Layout für eine Timeout-Kategorie."""
        grp = QGroupBox(title)
        bold = QFont()
        bold.setBold(True)
        grp.setFont(bold)

        grid = QGridLayout(grp)
        grid.setSpacing(6)
        grid.setContentsMargins(12, 14, 12, 10)

        # Spalten: 0=Aktiv, 1=Label, 2=SpinBox, 3=Einheit, 4=Standard, 5=Reset, 6=Info
        grid.setColumnMinimumWidth(0, 70)   # Aktiv-Checkbox
        grid.setColumnStretch(1, 1)         # Label bekommt Platz
        grid.setColumnMinimumWidth(2, 90)   # SpinBox
        grid.setColumnMinimumWidth(3, 40)   # "Min"
        grid.setColumnMinimumWidth(4, 150)  # Standard-Anzeige
        grid.setColumnMinimumWidth(5, 40)   # Reset-Button
        grid.setColumnMinimumWidth(6, 28)   # Info-Button

        normal_font = QFont()
        normal_font.setBold(False)

        for row, td in enumerate(entries):
            # Aktiv-Checkbox
            active_cb = QCheckBox("Aktiv")
            active_cb.setFont(normal_font)
            active_cb.setToolTip(f"Timeout für '{td.label}' anwenden")
            self._enabled_cbs[td.key] = active_cb
            grid.addWidget(active_cb, row, 0)

            # Label
            lbl = QLabel(td.label)
            lbl.setFont(normal_font)
            lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            grid.addWidget(lbl, row, 1)

            # SpinBox (in Minuten)
            spin = QSpinBox()
            spin.setFont(normal_font)
            spin.setRange(1, 600)          # 1 Min … 600 Min (10 Stunden)
            spin.setSingleStep(5)
            spin.setFixedWidth(85)
            spin.setAlignment(Qt.AlignmentFlag.AlignRight)
            spin.setToolTip(f"Timeout für '{td.label}' in Minuten (1–600)")
            self._spinboxes[td.key] = spin
            grid.addWidget(spin, row, 2)

            # Einheit
            unit_lbl = QLabel("Min")
            unit_lbl.setFont(normal_font)
            grid.addWidget(unit_lbl, row, 3)

            # Standard-Wert-Anzeige
            default_lbl = QLabel(f"Standard: {_format_default(td.default_s)}")
            default_lbl.setFont(normal_font)
            default_lbl.setStyleSheet("color: #888; font-size: 11px;")
            grid.addWidget(default_lbl, row, 4)

            # Reset-Button (einzeln)
            reset_btn = QPushButton("🔄")
            reset_btn.setFont(normal_font)
            reset_btn.setFixedSize(38, 28)
            reset_btn.setToolTip(
                f"Diesen Timeout auf Standard zurücksetzen und aktivieren "
                f"({_format_default(td.default_s)})"
            )
            reset_btn.setStyleSheet(
                "QPushButton { border: 1px solid #aaa; border-radius: 3px; font-size: 18px; }"
                "QPushButton:hover { background: #ddd; }"
            )
            # Lambda mit default-Argument um Closure-Problem zu vermeiden
            reset_btn.clicked.connect(
                lambda checked, k=td.key, s=spin, c=active_cb, d=td.default_s:
                    (s.setValue(_s_to_min(d)), c.setChecked(True))
            )
            grid.addWidget(reset_btn, row, 5)

            # Info-Button
            info_btn = InfoButton(td.description)
            info_btn.setFont(normal_font)
            grid.addWidget(info_btn, row, 6)

            active_cb.toggled.connect(spin.setEnabled)
            active_cb.toggled.connect(unit_lbl.setEnabled)
            active_cb.toggled.connect(default_lbl.setEnabled)

        return grp

    # ── Daten laden / speichern ──────────────────────────────────────────────

    def _load(self) -> None:
        """Lädt aktuelle Werte aus QSettings in alle SpinBoxen."""
        for td in TIMEOUT_DEFS:
            spin = self._spinboxes.get(td.key)
            if spin is not None:
                spin.setValue(_s_to_min(get_timeout_value(td.key)))
            cb = self._enabled_cbs.get(td.key)
            if cb is not None:
                cb.setChecked(is_timeout_enabled(td.key))

    def _save_and_accept(self) -> None:
        """Speichert alle Werte und schließt den Dialog."""
        values: dict[str, int] = {}
        enabled: dict[str, bool] = {}
        for td in TIMEOUT_DEFS:
            spin = self._spinboxes.get(td.key)
            if spin is not None:
                values[td.key] = _min_to_s(spin.value())
            cb = self._enabled_cbs.get(td.key)
            if cb is not None:
                enabled[td.key] = cb.isChecked()
        save_all_timeouts(values, enabled)
        self.accept()

    def _reset_all(self) -> None:
        """Setzt alle SpinBoxen auf Standardwerte zurück (noch nicht gespeichert)."""
        reply = QMessageBox.question(
            self,
            "Alle zurücksetzen?",
            "Möchtest du wirklich alle Timeouts auf ihre Standardwerte zurücksetzen?\n"
            "(Wird erst nach ‚OK' gespeichert.)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            for td in TIMEOUT_DEFS:
                spin = self._spinboxes.get(td.key)
                if spin is not None:
                    spin.setValue(_s_to_min(td.default_s))
                cb = self._enabled_cbs.get(td.key)
                if cb is not None:
                    cb.setChecked(True)
