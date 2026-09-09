# -*- coding: utf-8 -*-
"""
dragontools/gui/tab_manager.py

Dialog zum Ein-/Ausblenden von Tabs und Öffnen externer Programme.
Auch: Registerkarten-Zustand in QSettings persistieren.
"""
from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QCheckBox, QPushButton, QLabel,
    QFileDialog, QDialogButtonBox, QMessageBox,
)

from ..core.settings import APP_ORG, APP_NAME
from ..core.paths import EXE_DIR
from .ui_helpers import install_persistent_window_geometry

# QSettings-Keys für Tab-Sichtbarkeit
_KEY_PREFIX = "tabs/visible/"


# ---------------------------------------------------------------------------
# Externe Programme öffnen
# ---------------------------------------------------------------------------

def _open_external(exe_path: str) -> None:
    """Startet ein externes Programm ohne es einzubetten."""
    if not exe_path or not Path(exe_path).exists():
        return
    try:
        if sys.platform == "win32":
            os.startfile(exe_path)
        else:
            subprocess.Popen([exe_path])
    except Exception:
        pass


def _find_bundled_exe(name: str) -> str | None:
    """Sucht eine EXE im App-Bundle-Verzeichnis."""
    candidates = [
        EXE_DIR / "Daten" / "Programme" / name,
        EXE_DIR / "Daten" / "Programme" / "handbrake" / name,
        EXE_DIR / "Daten" / "Programme" / "rmts" / name,
        EXE_DIR / "Daten" / "Programme" / "mkvtoolnix" / name,
        EXE_DIR / name,
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


# ---------------------------------------------------------------------------
# Tab-Manager Dialog
# ---------------------------------------------------------------------------

class TabManagerDialog(QDialog):
    """
    Zeigt welche Tabs aktiv sind und lässt sie ein-/ausblenden.
    Auch: externe Programme starten.
    Änderungen werden sofort in QSettings gespeichert.
    """

    # Alle verfügbaren Tabs: (settings_key, Anzeige-Label)
    TABS = [
        ("h265",     "H.265 Konvertierung"),
        ("h264",     "H.264 Konvertierung"),
        ("av1",      "AV1 Konvertierung"),
        ("iso",      "ISO"),
        ("merge",    "Merge"),
        ("mp4_remux", "MP4-Remux"),
        ("audio_muxer", "Audio Muxer"),
        ("audio_video_matcher", "Audio-Video-Matcher"),
        ("subtitle", "Untertitel"),
        ("movie_renamer", "Renamer"),
        ("quality_tester", "Qualitätstester"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Registerkarten & externe Programme")
        self.setMinimumWidth(480)
        self._settings = QSettings(APP_ORG, APP_NAME)
        self._checks: dict[str, QCheckBox] = {}
        self._init_ui()
        install_persistent_window_geometry(self, "tab_manager_dialog", self._settings)

    def _init_ui(self) -> None:
        v = QVBoxLayout(self)

        # ── Registerkarten ────────────────────────────────────────────
        tab_grp = QGroupBox("Registerkarten (welche Tabs werden angezeigt?)")
        tg = QGridLayout(tab_grp)
        tg.addWidget(QLabel(
            "Deaktivierte Tabs werden beim nächsten Start nicht mehr geöffnet.\n"
            "Mind. ein Tab muss aktiv bleiben."
        ), 0, 0, 1, 2)
        for row, (key, label) in enumerate(self.TABS, start=1):
            cb = QCheckBox(label)
            cb.setChecked(self._settings.value(f"{_KEY_PREFIX}{key}", True, type=bool))
            self._checks[key] = cb
            tg.addWidget(cb, row, 0)
        v.addWidget(tab_grp)

        # ── Externe Programme ─────────────────────────────────────────
        ext_grp = QGroupBox("Externe Programme öffnen")
        eg = QVBoxLayout(ext_grp)
        eg.addWidget(QLabel(
            "Diese Programme werden außerhalb der App geöffnet\n"
            "(kein Einbetten – eigenes Fenster)."
        ))

        self._ext_buttons: list[tuple[str, str]] = [
            ("HandBrakeCLI / HandBrake.exe", "HandBrake.exe"),
            ("RenameMyTVSeries.exe (RMTS)",  "RenameMyTVSeries.exe"),
            ("MKVToolNix GUI (Remux)",       "mkvtoolnix-gui.exe"),
        ]

        for label, exe_name in self._ext_buttons:
            row = QHBoxLayout()
            btn = QPushButton(f"🚀 {label}")
            btn.clicked.connect(lambda _, n=exe_name: self._launch(n))
            row.addWidget(btn)
            eg.addLayout(row)

        # ── Web-Links ──────────────────────────────────────────────
        eg.addWidget(QLabel(""))  # Abstand
        eg.addWidget(QLabel("Web-Dienste:"))
        self._web_links: list[tuple[str, str]] = [
            ("🎬 The Movie Database (TMDB)", "https://www.themoviedb.org"),
        ]
        for label, url in self._web_links:
            row = QHBoxLayout()
            btn = QPushButton(label)
            btn.clicked.connect(lambda _, u=url: self._open_url(u))
            btn.setToolTip(url)
            row.addWidget(btn)
            eg.addLayout(row)

        v.addWidget(ext_grp)

        # ── Buttons ───────────────────────────────────────────────────
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _launch(self, exe_name: str) -> None:
        from ..core.paths import find_tool_in_settings
        # Mapping: exe_name → TOOL_KEYS-Schlüssel + mögliche Exe-Namen
        tool_map = {
            "HandBrake.exe":        ("handbrake", ["HandBrake.exe", "HandBrakeCLI.exe"]),
            "RenameMyTVSeries.exe": ("rmts",      ["RenameMyTVSeries.exe", "rmts.exe"]),
            "mkvtoolnix-gui.exe":   ("mkv",       ["mkvtoolnix-gui.exe"]),
        }
        # 1) Konfigurierter Ordner aus Einstellungen (settings_dialog)
        if exe_name in tool_map:
            tool_key, exe_names = tool_map[exe_name]
            result = find_tool_in_settings(tool_key, *exe_names)
            if result and Path(result).exists():
                _open_external(result); return
        # 2) Legacy direkt gespeicherter Pfad
        stored = self._settings.value(f"tools/external/{exe_name}", "", type=str)
        if stored and Path(stored).exists():
            _open_external(stored); return
        # 3) Im Bundle suchen
        found = _find_bundled_exe(exe_name)
        if found:
            _open_external(found); return
        # 4) Nutzer fragen (letzter Ausweg)
        path, _ = QFileDialog.getOpenFileName(
            self, f"{exe_name} wählen", "",
            f"Programm ({exe_name});;Alle Dateien (*)"
        )
        if path:
            self._settings.setValue(f"tools/external/{exe_name}", path)
            _open_external(path)

    def _open_url(self, url: str) -> None:
        """Öffnet eine URL im Standard-Browser."""
        import webbrowser
        webbrowser.open(url)

    def _save(self) -> None:
        active = [k for k, cb in self._checks.items() if cb.isChecked()]
        if not active:
            QMessageBox.warning(self, "Mind. 1 Tab", "Bitte mindestens einen Tab aktivieren.")
            return
        for key, cb in self._checks.items():
            self._settings.setValue(f"{_KEY_PREFIX}{key}", cb.isChecked())
        self.accept()


# ---------------------------------------------------------------------------
# Hilfsfunktion: welche Tabs sind laut Settings aktiv?
# ---------------------------------------------------------------------------

def get_visible_tabs() -> dict[str, bool]:
    s = QSettings(APP_ORG, APP_NAME)
    return {
        key: s.value(f"{_KEY_PREFIX}{key}", True, type=bool)
        for key, _ in TabManagerDialog.TABS
    }
