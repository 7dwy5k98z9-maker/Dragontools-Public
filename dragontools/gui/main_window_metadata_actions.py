# -*- coding: utf-8 -*-
from __future__ import annotations
import logging

from PyQt6.QtWidgets import QInputDialog, QMessageBox

from .online_metadata_action_workers import (
    OnlineMetadataConnectionTestThread,
    OnlineMetadataMovieSearchThread,
)




def _metadata_action_running(window) -> bool:
    thread = getattr(window, "_metadata_action_thread", None)
    return bool(thread is not None and thread.isRunning())


def _start_metadata_action_thread(window, thread, *, status_text: str) -> bool:
    if _metadata_action_running(window):
        QMessageBox.information(
            window,
            "Online-Metadaten",
            "Eine Online-Metadatenabfrage läuft bereits. Bitte deren Abschluss abwarten.",
        )
        thread.deleteLater()
        return False
    window._metadata_action_thread = thread
    try:
        window.statusBar().showMessage(status_text)
    except Exception:
        logging.getLogger(__name__).debug("Unterdrückte Best-Effort-Ausnahme in _start_metadata_action_thread.", exc_info=True)

    def cleanup() -> None:
        if getattr(window, "_metadata_action_thread", None) is thread:
            window._metadata_action_thread = None
        try:
            window.statusBar().clearMessage()
        except Exception:
            logging.getLogger(__name__).debug("Unterdrückte Best-Effort-Ausnahme in cleanup.", exc_info=True)
        thread.deleteLater()

    thread.finished.connect(cleanup)
    thread.start()
    return True


def stop_metadata_action_thread(window, *, timeout_ms: int = 8000) -> bool:
    thread = getattr(window, "_metadata_action_thread", None)
    if thread is None or not thread.isRunning():
        return True
    thread.requestInterruption()
    return bool(thread.wait(max(0, int(timeout_ms))))


class MainWindowMetadataActionsMixin:
    def _tmdb_client_or_warn(self, *, require_enabled: bool = False):
        from ..core.online_metadata import OnlineMetadataAuthError, client_from_settings_for

        try:
            return client_from_settings_for(self._settings, "movie", require_enabled=require_enabled)
        except OnlineMetadataAuthError as exc:
            QMessageBox.warning(
                self,
                "Metadaten nicht eingerichtet",
                f"{exc}\n\nÖffne Online-Metadaten → Metadaten-Zugriff einrichten.",
            )
            return None

    @staticmethod
    def _metadata_provider_label(provider: str) -> str:
        value = str(provider or "").strip().lower()
        if value == "both":
            return "TMDB + TheTVDB"
        if value == "thetvdb":
            return "TheTVDB"
        return "TMDB"

    def _test_tmdb_connection(self):
        from ..core.online_metadata import config_from_settings

        try:
            config = config_from_settings(self._settings, require_enabled=False)
        except Exception as exc:
            QMessageBox.warning(self, "Metadaten-Verbindung", f"Einstellungen konnten nicht gelesen werden: {exc}")
            return

        thread = OnlineMetadataConnectionTestThread(config, self)

        def completed(results_obj, errors_obj) -> None:
            results = [str(item) for item in list(results_obj or [])]
            errors = [str(item) for item in list(errors_obj or [])]
            if errors:
                QMessageBox.warning(
                    self,
                    "Metadaten-Verbindung fehlgeschlagen",
                    "\n".join(errors + results),
                )
                return
            QMessageBox.information(self, "Metadaten-Verbindung", "\n".join(results) or "Keine Quelle eingerichtet.")

        thread.completed.connect(completed)
        _start_metadata_action_thread(self, thread, status_text="Online-Metadatenverbindung wird geprüft …")

    def _search_online_metadata(self):
        from ..core.online_metadata import (
            OnlineMetadataAuthError,
            config_from_settings,
            format_movie_suggestion,
            parse_movie_query,
        )

        try:
            config = config_from_settings(self._settings, require_enabled=True, media_type="movie")
        except OnlineMetadataAuthError as exc:
            QMessageBox.warning(
                self,
                "Metadaten nicht eingerichtet",
                f"{exc}\n\nÖffne Online-Metadaten → Metadaten-Zugriff einrichten.",
            )
            return
        except Exception as exc:
            QMessageBox.warning(self, "Metadaten-Suche", f"Einstellungen konnten nicht gelesen werden: {exc}")
            return

        text, ok = QInputDialog.getText(
            self,
            "Titel online suchen",
            "Filmtitel oder Dateiname:",
        )
        if not ok or not text.strip():
            return
        query = parse_movie_query(text)
        thread = OnlineMetadataMovieSearchThread(config, query.title, query.year, self)

        def completed(suggestion, error_text: str) -> None:
            if error_text:
                QMessageBox.warning(self, "Metadaten-Suche fehlgeschlagen", str(error_text))
                return
            QMessageBox.information(
                self,
                "Metadaten-Treffer",
                format_movie_suggestion(suggestion),
            )

        thread.completed.connect(completed)
        _start_metadata_action_thread(self, thread, status_text="Online-Metadaten werden gesucht …")

    def _clear_metadata_cache(self):
        from ..core.online_metadata import clear_default_metadata_cache

        count = clear_default_metadata_cache()
        QMessageBox.information(
            self,
            "Metadaten-Cache",
            f"{count} Metadaten-Cache-Datei(en) gelöscht.",
        )
