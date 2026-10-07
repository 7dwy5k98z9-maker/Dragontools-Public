# -*- coding: utf-8 -*-
"""Coordinated shutdown gate for the DragonTools main window."""
from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox

from .application_shutdown import shutdown_loaded_widgets
from .application_worker_sources import application_worker_sources
from .jellyfin_refresh_dispatch import (
    stop_jellyfin_workers, begin_jellyfin_shutdown, finish_jellyfin_shutdown,
)
from .main_window_metadata_actions import stop_metadata_action_thread
import time
from .watch_folder_main_window_bridge import stop_watch_folder_controller


def prepare_main_window_close(window, *, timeout_ms: int = 8000) -> bool:
    """Stop background work cooperatively before the main window is allowed to close."""
    if getattr(window, "_tab_load_in_progress", None):
        QMessageBox.warning(window, "Registerkarte wird geladen",
            "Eine Registerkarte wird noch initialisiert. Bitte kurz warten und erneut schließen.")
        return False
    # Close intake first, even when a conversion worker needs another close
    # attempt. Otherwise scans can refill queues while workers are draining.
    deadline = time.monotonic() + max(0, int(timeout_ms)) / 1000
    remaining = lambda: max(0, int((deadline - time.monotonic()) * 1000))
    begin_jellyfin_shutdown()
    try:
        ok = _close_with_budget(window, remaining)
    except Exception as exc:
        finish_jellyfin_shutdown(False)
        QMessageBox.warning(window, "DragonTools wird noch beendet",
            f"Worker-Zustand konnte nicht sicher ermittelt werden. Das Fenster bleibt geöffnet.\n\n{exc}")
        return False
    finish_jellyfin_shutdown(ok)
    return ok


def _close_with_budget(window, remaining):
    stop_watch_folder_controller(window, timeout_ms=0)
    result = shutdown_loaded_widgets(application_worker_sources(window), timeout_ms=remaining())
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

    if not stop_metadata_action_thread(window, timeout_ms=remaining()):
        QMessageBox.warning(
            window,
            "Online-Abfrage wird noch beendet",
            "Eine Online-Metadatenabfrage ist noch in einem Netzwerkaufruf. "
            "Das Fenster bleibt geöffnet, bis der Aufruf sauber beendet ist.",
        )
        return False

    if not stop_watch_folder_controller(window, timeout_ms=remaining()):
        QMessageBox.warning(
            window,
            "Watch-Folder wird noch beendet",
            "Der Watch-Folder-Scan reagiert noch auf einen Dateisystemzugriff. "
            "Das Fenster bleibt geöffnet, bis der Scan sauber beendet ist.",
        )
        return False
    if not stop_jellyfin_workers(timeout_ms=remaining()):
        QMessageBox.warning(
            window, "Jellyfin wird noch beendet",
            "Eine Jellyfin-Abfrage ist noch aktiv. Das Fenster bleibt bis zum Ende des Netzwerkaufrufs geöffnet.",
        )
        return False
    # Qt event delivery while waiting may register another worker. Re-read
    # the public ownership sources before allowing their QObject parents to die.
    final = shutdown_loaded_widgets(application_worker_sources(window), timeout_ms=remaining())
    if not final.ok:
        QMessageBox.warning(window, "DragonTools wird noch beendet",
            "Während des Beendens wurde weitere Hintergrundarbeit registriert. "
            "Das Fenster bleibt geöffnet.\n\nNoch aktiv: " + ", ".join(final.still_running))
        return False
    return True


__all__ = ["prepare_main_window_close"]
