# -*- coding: utf-8 -*-
"""DragonTools-Hauptfenster: schlanke Composition-Root für Menüs, Aktionen, Tabs und Recovery."""
from __future__ import annotations

import ctypes
import sys
import traceback

from PyQt6.QtCore import QSettings, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QMainWindow, QMessageBox, QWidget

from ..core.crash_guard import clear_activity
from ..core.settings_app import APP_ORG, APP_NAME
from ..core.version import APP_VERSION
from ..core.resource_paths import EXE_DIR, BASE
from ..core.path_defaults import ensure_default_storage_dirs
from ..core.tool_paths import get_tool_paths
from .styles import STYLE_LIGHT
from .main_window_actions import MainWindowActionsMixin
from .main_window_menus import MainWindowMenuMixin
from .main_window_tabs import MainWindowTabsMixin
from .main_window_recovery import MainWindowRecoveryMixin
from .windows_restart_guard import install_windows_restart_guard
from .watch_folder_main_window_bridge import start_watch_folder_controller
from .main_window_shutdown import prepare_main_window_close


class MainWindow(
    MainWindowMenuMixin,
    MainWindowActionsMixin,
    MainWindowTabsMixin,
    MainWindowRecoveryMixin,
    QMainWindow,
):
    """Composition-Root der Desktop-GUI; Fachlogik liegt in fokussierten Mixins/Services."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"© 2026 – Dragon Tools V{APP_VERSION}")
        self.resize(1100, 780)
        self._settings  = QSettings(APP_ORG, APP_NAME)
        self._dark       = False
        self._tab_widgets: dict[str, QWidget | None] = {}   # Lazy Loading Cache
        self._closed_tabs: list[tuple[str, int]] = []        # für Ctrl+Shift+T

        # ToolPaths-Singleton einmalig mit Qt-Provider initialisieren.
        # Alle späteren get_tool_paths()-Aufrufe (Worker, Settings-Dialog usw.)
        # erhalten dieselbe gecachte Instanz – ohne Qt-Abhängigkeit im core-Paket.
        from .tool_path_settings import QtToolPathSettingsProvider
        get_tool_paths(provider=QtToolPathSettingsProvider())
        try:
            ensure_default_storage_dirs()
        except OSError as exc:
            QMessageBox.warning(
                self,
                "Standardordner nicht anlegbar",
                "Die Standard-Speicherordner unter Dokumente\\DragonTools\\Ausgabe "
                f"konnten nicht angelegt werden.\n\n{exc}",
            )

        self._set_icon()
        self.setStyleSheet(STYLE_LIGHT)
        self._init_menu()
        self._init_tabs()
        self._init_shortcuts()
        self._restore()
        start_watch_folder_controller(self)
        install_windows_restart_guard(self)
        # Fenster beim Start immer sichtbar in den Vordergrund holen.
        # QTimer.singleShot(0) stellt sicher, dass das Fenster erst vollständig
        # initialisiert und vom Event-Loop gerendert ist, bevor raise_/
        # activateWindow() greifen – sonst kann der Fokus-Aufruf ins Leere laufen.
        QTimer.singleShot(0, lambda: bring_to_front(self))
        QTimer.singleShot(900, self._maybe_show_recovery_journals)
        QTimer.singleShot(1600, self._maybe_show_replacement_reminders)
        QTimer.singleShot(2800, self._check_for_updates_on_startup)

    def _set_icon(self):
        for c in (
            EXE_DIR  / "Daten" / "icon" / "Feuerdrache.ico",
            EXE_DIR  / "icon"  / "Feuerdrache.ico",
            BASE     / "icon"  / "Feuerdrache.ico",
        ):
            if c.exists():
                self.setWindowIcon(QIcon(str(c))); return

    def _restore(self):
        g = self._settings.value("main/geometry")
        if g: self.restoreGeometry(g)

    def closeEvent(self, e):
        if not prepare_main_window_close(self):
            e.ignore()
            return
        self._settings.setValue("main/geometry", self.saveGeometry())
        self._settings.sync()
        clear_activity()
        super().closeEvent(e)


def bring_to_front(win: QMainWindow) -> None:
    win.showNormal(); win.raise_(); win.activateWindow()
    if sys.platform == "win32":
        try:
            hwnd=int(win.winId()); u=ctypes.windll.user32
            u.AllowSetForegroundWindow(-1); u.ShowWindow(hwnd,5); u.SetForegroundWindow(hwnd)
        except Exception as e:
            print(f"[WARN] bring_to_front() fehlgeschlagen: {e}", file=sys.stderr)
            traceback.print_exc()
