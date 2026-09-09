# -*- coding: utf-8 -*-
"""
dragontools/gui/convert_widget_custom_widgets.py

Ausgelagerte Custom-Widgets für das ConvertWidget:
    - BannerLabel       : Proportionales Banner-Bild
    - DragonProgressBar : Feuer-Gradient Progressbar mit Glow
    - PathRow           : Pfad-Zeile mit Aktiv-Checkbox / Browse-Button

Dazu kommen die kleinen Helfer:
    - _find_banner_single(): sucht die banner.png an bekannten Orten
    - _eta(seconds)         : formatiert Sekunden als H:MM:SS / MM:SS
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import (
    QPixmap, QPainter, QColor, QLinearGradient, QPen, QPainterPath,
)
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QLineEdit, QCheckBox, QPushButton,
    QProgressBar, QFileDialog, QSizePolicy, QStackedWidget,
)

from ..core.paths import EXE_DIR, BASE
from .info_button import InfoButton


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def _eta(s) -> str:
    """Formatiert Sekunden als H:MM:SS bzw. MM:SS (oder '' bei <=0)."""
    if not s or s <= 0:
        return ""
    s = int(s)
    m, sec = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def _find_banner_single() -> str | None:
    """Sucht die banner.png in den bekannten Ressourcen-Ordnern."""
    for root in (
        EXE_DIR / "Daten" / "Bilder",
        EXE_DIR / "Bilder",
        BASE / "Bilder",
    ):
        p = root / "banner.png"
        if p.exists():
            return str(p)
    return None


# ------------------------------------------------------------------
# BannerLabel
# ------------------------------------------------------------------
class BannerLabel(QLabel):
    """
    Zeigt ein Pixmap proportional an, ohne Verzerrung.
    Standardmodus: Bild komplett sichtbar einpassen.
    Optional: auf Höhe einpassen, falls ein schmaler Banner-Effekt gewünscht ist.
    """

    def __init__(self, parent=None, *, scale_mode: str = "contain"):
        super().__init__(parent)
        self._pix = QPixmap()
        self._scale_mode = scale_mode
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def setBannerPixmap(self, pixmap: QPixmap) -> None:
        self._pix = pixmap
        self._update_scaled()

    def setScaleMode(self, mode: str) -> None:
        self._scale_mode = mode if mode in {"contain", "fit_height"} else "contain"
        self._update_scaled()

    def sourceAspectRatio(self) -> float:
        if self._pix.isNull() or self._pix.height() <= 0:
            return 0.0
        return self._pix.width() / self._pix.height()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_scaled()

    def _update_scaled(self) -> None:
        if self._pix.isNull() or self.width() <= 0 or self.height() <= 0:
            return
        if self._scale_mode == "fit_height":
            scaled = self._pix.scaledToHeight(
                self.height(),
                Qt.TransformationMode.SmoothTransformation,
            )
            if scaled.width() > self.width():
                scaled = self._pix.scaledToWidth(
                    self.width(),
                    Qt.TransformationMode.SmoothTransformation,
                )
        else:
            scaled = self._pix.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self.setPixmap(scaled)


# ------------------------------------------------------------------
# DragonProgressBar
# ------------------------------------------------------------------
class DragonProgressBar(QProgressBar):
    """
    Custom ProgressBar mit:
    - dunklem Track
    - Feuer-Gradient
    - leichtem Glow
    - runden Ecken
    - sauberem Text-Rendering
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRange(0, 100)
        self.setTextVisible(True)
        self.setMinimumHeight(24)
        self.setMaximumHeight(24)
        self.setStyleSheet("QProgressBar { background: transparent; border: none; }")

    def paintEvent(self, event):
        maximum = self.maximum()
        minimum = self.minimum()
        value = self.value()

        total = max(1, maximum - minimum)
        progress = (value - minimum) / total
        progress = max(0.0, min(1.0, progress))

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = self.rect().adjusted(1, 1, -1, -1)
        radius = rect.height() / 2.0

        # --- Hintergrund-Track ---
        track_path = QPainterPath()
        track_path.addRoundedRect(QRectF(rect), radius, radius)

        track_gradient = QLinearGradient(
            rect.left(), rect.top(), rect.left(), rect.bottom()
        )
        track_gradient.setColorAt(0.0, QColor("#2f2f2f"))
        track_gradient.setColorAt(0.5, QColor("#262626"))
        track_gradient.setColorAt(1.0, QColor("#1f1f1f"))

        painter.fillPath(track_path, track_gradient)

        # Subtile Aussenkante
        painter.setPen(QPen(QColor(255, 255, 255, 30), 1))
        painter.drawPath(track_path)

        # --- Fortschritt ---
        if progress > 0:
            fill_width = rect.width() * progress
            fill_rect = QRectF(rect.left(), rect.top(), fill_width, rect.height())

            fill_path = QPainterPath()
            fill_path.addRoundedRect(fill_rect, radius, radius)

            # Glow hinter dem Balken
            glow_gradient = QLinearGradient(
                fill_rect.left(), fill_rect.top(),
                fill_rect.right(), fill_rect.top(),
            )
            glow_gradient.setColorAt(0.0, QColor(255, 40, 40, 170))
            glow_gradient.setColorAt(0.55, QColor(255, 122, 0, 200))
            glow_gradient.setColorAt(1.0, QColor(255, 196, 0, 170))

            painter.save()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.fillPath(fill_path, glow_gradient)
            painter.restore()

            # Echter Aussen-Glow
            glow_rect = QRectF(
                fill_rect.left() - 6,
                fill_rect.top() - 5,
                fill_rect.width() + 10,
                fill_rect.height() + 8,
            )

            glow_path = QPainterPath()
            glow_path.addRoundedRect(glow_rect, radius + 3, radius + 3)

            outer_glow = QLinearGradient(
                glow_rect.left(), glow_rect.top(),
                glow_rect.right(), glow_rect.top(),
            )
            outer_glow.setColorAt(0.0, QColor(255, 60, 20, 70))
            outer_glow.setColorAt(0.55, QColor(255, 140, 0, 110))
            outer_glow.setColorAt(1.0, QColor(255, 210, 80, 70))

            painter.save()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.fillPath(glow_path, outer_glow)
            painter.restore()

            # Eigentliche Feuerflaeche
            fire_gradient = QLinearGradient(
                fill_rect.left(), fill_rect.top(),
                fill_rect.right(), fill_rect.top(),
            )
            fire_gradient.setColorAt(0.0, QColor("#ff1f1f"))
            fire_gradient.setColorAt(0.45, QColor("#ff5e1a"))
            fire_gradient.setColorAt(0.75, QColor("#ff9a1f"))
            fire_gradient.setColorAt(1.0, QColor("#ffd24a"))

            painter.fillPath(fill_path, fire_gradient)

            # Heller Highlight-Streifen oben
            highlight_rect = QRectF(
                fill_rect.left(),
                fill_rect.top() + 1,
                fill_rect.width(),
                max(2.0, fill_rect.height() * 0.35),
            )
            highlight_path = QPainterPath()
            highlight_path.addRoundedRect(highlight_rect, radius, radius)

            highlight_gradient = QLinearGradient(
                highlight_rect.left(), highlight_rect.top(),
                highlight_rect.left(), highlight_rect.bottom(),
            )
            highlight_gradient.setColorAt(0.0, QColor(255, 255, 255, 90))
            highlight_gradient.setColorAt(1.0, QColor(255, 255, 255, 0))

            painter.fillPath(highlight_path, highlight_gradient)

        # --- Text ---
        text = self.format()
        text = text.replace("%p", str(int(progress * 100)))
        text = text.replace("%v", str(value))
        text = text.replace("%m", str(maximum))

        painter.setPen(QColor("#f2f2f2"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)


# ------------------------------------------------------------------
# PathRow
# ------------------------------------------------------------------
class PathRow(QWidget):
    """
    Pfad-Zeile: [check] [TV:]  [___Pfad___]  [...]  [i]
    Status wird NUR über QStackedWidget gesteuert:
      Index 0 = Pfad-LineEdit (aktiv)
      Index 1 = Label "Deaktiviert" (rot)
    Das lbl (TV:/Anime:/Film:) bekommt KEINEN setStyleSheet-Aufruf mehr.
    Stattdessen: dezente Opacity via setEnabled auf dem Label-Container.
    """

    def __init__(self, label: str, key: str, info: str, parent=None):
        super().__init__(parent)
        self.key = key
        self._saved_path = ""

        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)

        self.cb = QCheckBox()
        self.cb.setChecked(True)
        self.cb.setToolTip("Pfad aktivieren / deaktivieren")

        # Label in eigenem Container damit setEnabled den Container graut
        # NICHT das Label direkt - so greift Qt-System-Grau korrekt
        self._lbl_container = QWidget()
        self._lbl_container.setFixedWidth(54)
        lc = QHBoxLayout(self._lbl_container)
        lc.setContentsMargins(0, 0, 0, 0)
        self.lbl = QLabel(label)
        lc.addWidget(self.lbl)

        # Stack 0: aktives Eingabefeld
        self._stack = QStackedWidget()
        self._stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.edit = QLineEdit()
        self._stack.addWidget(self.edit)

        # Stack 1: Deaktiviert-Anzeige (roter Text)
        self._dis = QLabel("⛔  Deaktiviert")
        self._dis.setStyleSheet(
            "color: #c0392b; font-weight: bold; "
            "background: #fff0f0; border: 1px solid #e74c3c; "
            "border-radius: 3px; padding: 3px 8px;"
        )
        self._stack.addWidget(self._dis)

        self._browse_btn = QPushButton("…")
        self._browse_btn.setFixedWidth(28)
        self._browse_btn.clicked.connect(self._browse)

        ib = InfoButton(info)

        self.cb.toggled.connect(self._apply_state)

        h.addWidget(self.cb)
        h.addWidget(self._lbl_container)
        h.addWidget(self._stack, 1)
        h.addWidget(self._browse_btn)
        h.addWidget(ib)

        # Initialen Zustand setzen NACH dem Layout-Aufbau
        self._apply_state(True)

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Ordner wählen", self.edit.text())
        if d:
            self.edit.setText(d)

    def _apply_state(self, on: bool) -> None:
        if on:
            self._stack.setCurrentIndex(0)
            self.edit.setEnabled(True)
            self._browse_btn.setEnabled(True)
            # Container aktivieren -> Qt setzt Textfarbe automatisch normal
            self._lbl_container.setEnabled(True)
            if not self.edit.text().strip() and self._saved_path:
                self.edit.setText(self._saved_path)
        else:
            self._saved_path = self.edit.text()
            self._stack.setCurrentIndex(1)
            self.edit.setEnabled(False)
            self._browse_btn.setEnabled(False)
            # Container deaktivieren -> Qt graut den Text systemseitig aus
            self._lbl_container.setEnabled(False)

    def set_text(self, text: str) -> None:
        self.edit.setText(text)

    setText = set_text   # Alias

    def text(self) -> str:
        return self.edit.text()

    @property
    def active(self) -> bool:
        return self.cb.isChecked()

    @property
    def path(self) -> str | None:
        if not self.active:
            return None
        return self.edit.text().strip() or None
