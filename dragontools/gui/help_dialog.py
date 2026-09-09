# -*- coding: utf-8 -*-
"""dragontools/gui/help_dialog.py

WICHTIG: setSource() NICHT verwenden - das navigiert zur URL und
         überschreibt den Inhalt (weißes/graues leeres Fenster).
         Stattdessen: document().setBaseUrl() + setHtml()
"""
from __future__ import annotations
import sys, webbrowser
from pathlib import Path
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTextBrowser,
)
from ..core.paths import EXE_DIR, BASE
from ..core.settings import APP_VERSION
from .ui_helpers import install_persistent_window_geometry

FROZEN = bool(getattr(sys, "frozen", False))


def _find_help() -> str | None:
    candidates = [
        BASE  / "help.html",
        EXE_DIR / "help.html",
        EXE_DIR / "Daten" / "help.html",
        EXE_DIR / "Hilfedatei" / "help.html",
        Path("help.html").resolve(),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Dragon Tools V{APP_VERSION} – Hilfe")
        self.resize(980, 720)
        self._help_path = _find_help()
        self._init_ui()
        install_persistent_window_geometry(self, "help_dialog")

    def _init_ui(self):
        v = QVBoxLayout(self)

        # QWebEngineView nur im Dev-Modus
        web_ok = False
        if self._help_path and not FROZEN:
            try:
                from PyQt6.QtWebEngineWidgets import QWebEngineView
                self._view = QWebEngineView()
                self._view.load(QUrl.fromLocalFile(
                    str(Path(self._help_path).resolve())))
                v.addWidget(self._view)
                web_ok = True
            except Exception:
                pass

        if not web_ok:
            self._browser = QTextBrowser()
            self._browser.setOpenExternalLinks(True)

            if self._help_path:
                try:
                    html = Path(self._help_path).read_text(
                        encoding="utf-8", errors="replace")

                    # Basis-URL für interne Ressourcen setzen
                    # WICHTIG: document().setBaseUrl() statt setSource()!
                    # setSource() wuerde zur URL navigieren → leere Seite
                    base_url = QUrl.fromLocalFile(
                        str(Path(self._help_path).resolve().parent) + "/")
                    self._browser.document().setBaseUrl(base_url)

                    # HTML laden
                    self._browser.setHtml(html)

                except Exception as e:
                    self._browser.setPlainText(
                        f"Hilfe-Datei nicht lesbar:\n{self._help_path}\n\nFehler: {e}")
            else:
                self._browser.setPlainText(
                    "Keine Hilfe-Datei gefunden.\n"
                    "Bitte 'help.html' ins Programmverzeichnis legen.")

            v.addWidget(self._browser)

        btn_row = QHBoxLayout()
        browser_btn = QPushButton("🌐 Im Browser öffnen")
        browser_btn.clicked.connect(self._open_browser)
        browser_btn.setEnabled(bool(self._help_path))
        close_btn = QPushButton("Schließen")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(browser_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        v.addLayout(btn_row)

    def _open_browser(self):
        if not self._help_path: return
        try:
            webbrowser.open(QUrl.fromLocalFile(
                str(Path(self._help_path).resolve())).toString())
        except Exception:
            pass
