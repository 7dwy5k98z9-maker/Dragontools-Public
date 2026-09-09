# -*- coding: utf-8 -*-
"""
Qt-Implementierung des ToolPathSettingsProvider.

Diese Datei gehoert zur GUI-Schicht und ist die einzige Stelle im Projekt,
die für ToolPaths Qt (QSettings) importiert.

Warum hier und nicht in core/paths.py?
    Das core-Paket soll keine Qt-Abhängigkeit haben, damit Worker-Code,
    Tests und spaetere CLI-Nutzung ohne Qt-Eventloop funktionieren.
    core.paths.ToolPathSettingsProvider definiert das Interface (kein Qt).
    Diese Klasse implementiert es mit QSettings.

Verwendung (einmalig beim App-Start in main_window.py):

    from dragontools.gui.tool_path_settings import QtToolPathSettingsProvider
    from dragontools.core.paths import get_tool_paths

    get_tool_paths(provider=QtToolPathSettingsProvider())

Danach liefern alle get_tool_paths()-Aufrufe die gecachte Instanz zurück.
Nach invalidate_tool_paths() (beim Speichern der Einstellungen) wird der
Singleton neu erzeugt – der Provider wird wiederverwendet und liest dann
die aktuellen Werte aus QSettings.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSettings

from ..core.paths import ToolPathSettingsProvider
from ..core.settings import APP_ORG, APP_NAME, TOOL_KEYS


class QtToolPathSettingsProvider(ToolPathSettingsProvider):
    """Liest benutzerdefinierte Tool-Verzeichnisse aus QSettings.

    Legt absichtlich KEINE QSettings-Instanz beim Init an, sondern
    erzeugt pro Aufruf eine neue. Das stellt sicher, dass nach
    invalidate_tool_paths() + Neuinitialisierung des Singletons immer
    die aktuell gespeicherten Werte gelesen werden – nie ein veralteter
    Snapshot vom App-Start.
    """

    def get_custom_dirs(self) -> list[Path]:
        """Gibt alle konfigurierten Tool-Verzeichnisse zurück die tatsächlich existieren."""
        s = QSettings(APP_ORG, APP_NAME)
        dirs: list[Path] = []
        for _tool, (_use_key, dir_key) in TOOL_KEYS.items():
            dir_val = s.value(dir_key, "", type=str)
            if dir_val and dir_val.strip():
                p = Path(dir_val.strip())
                if p.exists():
                    dirs.append(p)
        return dirs

    def find_in_settings(self, tool_key: str, *exe_names: str) -> str | None:
        """Sucht ein bestimmtes Executable im konfigurierten Tool-Verzeichnis.

        Gibt den vollständigen Pfad zurück oder None wenn der Ordner nicht
        konfiguriert ist oder das Executable nicht gefunden wurde.
        """
        if tool_key not in TOOL_KEYS:
            return None
        _, dir_key = TOOL_KEYS[tool_key]
        s = QSettings(APP_ORG, APP_NAME)
        dir_val = s.value(dir_key, "", type=str)
        if not dir_val or not dir_val.strip():
            return None
        tool_dir = Path(dir_val.strip())
        for name in exe_names:
            p = tool_dir / name
            if p.is_file():
                return str(p)
        try:
            for child in tool_dir.iterdir():
                if not child.is_dir():
                    continue
                for name in exe_names:
                    p = child / name
                    if p.is_file():
                        return str(p)
        except Exception:
            pass
        return None
