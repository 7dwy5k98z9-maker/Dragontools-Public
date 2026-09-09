# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QInputDialog, QMessageBox


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
        from ..core.online_metadata import (
            OnlineMetadataAuthError,
            OnlineMetadataError,
            client_from_config,
            config_from_settings,
            metadata_provider_configured,
        )

        try:
            config = config_from_settings(self._settings, require_enabled=False)
        except Exception as exc:
            QMessageBox.warning(self, "Metadaten-Verbindung", f"Einstellungen konnten nicht gelesen werden: {exc}")
            return

        results: list[str] = []
        errors: list[str] = []
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for media_type, label in (("movie", "Filme"), ("series", "Serien")):
                if not metadata_provider_configured(config, media_type):
                    provider_label = self._metadata_provider_label(config.provider_for(media_type))
                    results.append(f"{label}: {provider_label} nicht vollständig eingerichtet")
                    continue
                try:
                    client = client_from_config(config, media_type)
                    provider_label = getattr(client, "provider_label", self._metadata_provider_label(config.provider_for(media_type)))
                    client.test_connection()
                    results.append(f"{label}: {provider_label} OK")
                except (OnlineMetadataAuthError, OnlineMetadataError) as exc:
                    errors.append(f"{label}: {provider_label} fehlgeschlagen - {exc}")
                except Exception as exc:
                    errors.append(f"{label}: {provider_label} unerwarteter Fehler - {exc}")
        finally:
            QApplication.restoreOverrideCursor()
        if errors:
            QMessageBox.warning(
                self,
                "Metadaten-Verbindung fehlgeschlagen",
                "\n".join(errors + results),
            )
            return
        QMessageBox.information(self, "Metadaten-Verbindung", "\n".join(results) or "Keine Quelle eingerichtet.")

    def _search_online_metadata(self):
        from ..core.online_metadata import (
            OnlineMetadataError,
            format_movie_suggestion,
            parse_movie_query,
        )

        client = self._tmdb_client_or_warn()
        if client is None:
            return
        text, ok = QInputDialog.getText(
            self,
            "Titel online suchen",
            "Filmtitel oder Dateiname:",
        )
        if not ok or not text.strip():
            return
        query = parse_movie_query(text)
        error_text = ""
        suggestion = None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            suggestion = client.resolve_movie(query.title, year=query.year)
        except OnlineMetadataError as exc:
            error_text = str(exc)
        finally:
            QApplication.restoreOverrideCursor()
        if error_text:
            QMessageBox.warning(self, "Metadaten-Suche fehlgeschlagen", error_text)
            return
        QMessageBox.information(
            self,
            "Metadaten-Treffer",
            format_movie_suggestion(suggestion),
        )

    def _clear_metadata_cache(self):
        from ..core.online_metadata import clear_default_metadata_cache

        count = clear_default_metadata_cache()
        QMessageBox.information(
            self,
            "Metadaten-Cache",
            f"{count} Metadaten-Cache-Datei(en) gelöscht.",
        )
