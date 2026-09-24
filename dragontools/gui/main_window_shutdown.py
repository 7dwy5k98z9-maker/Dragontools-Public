# -*- coding: utf-8 -*-
"""Coordinated shutdown gate for the DragonTools main window."""
from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox

from .application_shutdown import shutdown_loaded_widgets
from .jellyfin_refresh_dispatch import stop_jellyfin_workers
from .main_window_metadata_actions import stop_metadata_action_thread
from .watch_folder_main_window_bridge import stop_watch_folder_controller


def prepare_main_window_close(window, *, timeout_ms: int = 8000) -> bool:
    """Stop background work cooperatively before the main window is allowed to close."""
    result = shutdown_loaded_widgets(window._tab_widgets.values(), timeout_ms=timeout_ms)
    if not result.ok:
        QMessageBox.warning(
            window,
            "DragonTools wird noch beendet",
            "Mindestens ein Worker läuft noch und konnte innerhalb des "
            "Shutdown-Zeitfensters nicht sauber beendet werden.\n\n"
            "Das Fenster bleibt aus Sicherheitsgründen geöffnet. Bitte kurz warten "
            "und erneut schließen.\n\nNoch aktiv: " + ", ".join(result.still_running),
        )
        return False

    if not stop_metadata_action_thread(window, timeout_ms=timeout_ms):
        QMessageBox.warning(
            window,
            "Online-Abfrage wird noch beendet",
            "Eine Online-Metadatenabfrage ist noch in einem Netzwerkaufruf. "
            "Das Fenster bleibt geöffnet, bis der Aufruf sauber beendet ist.",
        )
        return False

    if not stop_watch_folder_controller(window):
        QMessageBox.warning(
            window,
            "Watch-Folder wird noch beendet",
            "Der Watch-Folder-Scan reagiert noch auf einen Dateisystemzugriff. "
            "Das Fenster bleibt geöffnet, bis der Scan sauber beendet ist.",
        )
        return False
    if not stop_jellyfin_workers(timeout_ms=timeout_ms):
        QMessageBox.warning(
            window, "Jellyfin wird noch beendet",
            "Eine Jellyfin-Abfrage ist noch aktiv. Das Fenster bleibt bis zum Ende des Netzwerkaufrufs geöffnet.",
        )
        return False
    return True


__all__ = ["prepare_main_window_close"]
