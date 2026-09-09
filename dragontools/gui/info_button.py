# -*- coding: utf-8 -*-
"""
dragontools/gui/info_button.py
Kleines ℹ️-Icon das einen Tooltip-ähnlichen Popup zeigt.
Einheitlich für alle Felder nutzbar: InfoButton("Erklärungstext")
"""
from __future__ import annotations
from PyQt6.QtWidgets import QPushButton, QToolTip, QHBoxLayout, QWidget, QLabel


class InfoButton(QPushButton):
    """Kleines ℹ️-Icon. Klick oder Hover zeigt den Erklärungstext."""

    def __init__(self, text: str, parent=None):
        super().__init__("ℹ️", parent)
        self._text = text
        self.setFixedSize(22, 22)
        self.setFlat(True)
        self.setStyleSheet("""
            QPushButton { border: none; background: transparent;
                          font-size: 13px; padding: 0; }
            QPushButton:hover { color: #0078d7; }
        """)
        self.setToolTip(text)
        self.clicked.connect(self._show_popup)

    def _show_popup(self) -> None:
        QToolTip.showText(self.mapToGlobal(self.rect().bottomLeft()), self._text, self)


def labeled_row(label: str, widget: QWidget, info: str) -> QWidget:
    """
    Erstellt eine Zeile: [Label] [Widget] [ℹ️]
    Gibt ein QWidget zurück das direkt in ein Layout eingefügt werden kann.
    """
    container = QWidget()
    h = QHBoxLayout(container)
    h.setContentsMargins(0, 0, 0, 0)
    h.addWidget(QLabel(label))
    h.addWidget(widget, 1)
    h.addWidget(InfoButton(info))
    return container
