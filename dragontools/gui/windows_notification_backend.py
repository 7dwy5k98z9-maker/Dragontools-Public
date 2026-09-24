# -*- coding: utf-8 -*-
"""Native Windows notification delivery through Qt's system-tray abstraction."""
from __future__ import annotations
import logging

import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon


class WindowsNotificationBackend:
    """Show best-effort Windows notifications without adding a Python dependency."""

    def __init__(self, parent=None) -> None:
        self._parent = parent
        self._tray: QSystemTrayIcon | None = None
        self._hide_timer = QTimer(parent)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide)

    def show(self, title: str, message: str, level: str = "info") -> bool:
        if sys.platform != "win32" or not QSystemTrayIcon.isSystemTrayAvailable():
            return False
        try:
            tray = self._ensure_tray()
            icon = {
                "error": QSystemTrayIcon.MessageIcon.Critical,
                "warning": QSystemTrayIcon.MessageIcon.Warning,
            }.get(str(level or "").lower(), QSystemTrayIcon.MessageIcon.Information)
            tray.show()
            tray.showMessage(str(title or "Dragon Tools"), str(message or ""), icon, 7000)
            self._hide_timer.start(10000)
            return True
        except Exception:
            self._hide()
            return False

    def _ensure_tray(self) -> QSystemTrayIcon:
        if self._tray is not None:
            return self._tray
        tray = QSystemTrayIcon(self._parent)
        icon = QApplication.windowIcon()
        if icon.isNull() and self._parent is not None and hasattr(self._parent, "windowIcon"):
            icon = self._parent.windowIcon()
        tray.setIcon(icon)
        tray.setToolTip("Dragon Tools")
        self._tray = tray
        return tray

    def _hide(self) -> None:
        if self._tray is not None:
            try:
                self._tray.hide()
            except Exception:
                logging.getLogger(__name__).debug("Unterdrückte Best-Effort-Ausnahme in _hide.", exc_info=True)
