# -*- coding: utf-8 -*-
"""Non-blocking workers for manual online-metadata actions."""
from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal

from ..core.online_metadata import (
    OnlineMetadataAuthError,
    OnlineMetadataError,
    client_from_config,
    metadata_provider_configured,
)


def _provider_label(provider: str) -> str:
    value = str(provider or "").strip().lower()
    if value == "both":
        return "TMDB + TheTVDB"
    if value == "thetvdb":
        return "TheTVDB"
    return "TMDB"


class OnlineMetadataConnectionTestThread(QThread):
    """Tests movie/series provider access without blocking the GUI thread."""

    completed = pyqtSignal(object, object)  # results, errors

    def __init__(self, config, parent=None) -> None:
        super().__init__(parent)
        self._config = config

    def run(self) -> None:
        results: list[str] = []
        errors: list[str] = []
        config = self._config
        for media_type, label in (("movie", "Filme"), ("series", "Serien")):
            if self.isInterruptionRequested():
                return
            if not metadata_provider_configured(config, media_type):
                results.append(
                    f"{label}: {_provider_label(config.provider_for(media_type))} nicht vollständig eingerichtet"
                )
                continue
            provider_label = _provider_label(config.provider_for(media_type))
            try:
                client = client_from_config(config, media_type)
                provider_label = getattr(client, "provider_label", provider_label)
                client.test_connection()
                results.append(f"{label}: {provider_label} OK")
            except (OnlineMetadataAuthError, OnlineMetadataError) as exc:
                errors.append(f"{label}: {provider_label} fehlgeschlagen - {exc}")
            except Exception as exc:  # QThread boundary: surface unexpected provider errors.
                errors.append(f"{label}: {provider_label} unerwarteter Fehler - {exc}")
        if not self.isInterruptionRequested():
            self.completed.emit(results, errors)


class OnlineMetadataMovieSearchThread(QThread):
    """Resolves one movie query outside the GUI thread."""

    completed = pyqtSignal(object, str)  # suggestion | None, error text

    def __init__(self, config, title: str, year: int | None, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._title = str(title or "")
        self._year = year

    def run(self) -> None:
        if self.isInterruptionRequested():
            return
        try:
            client = client_from_config(self._config, "movie")
            suggestion = client.resolve_movie(self._title, year=self._year)
        except (OnlineMetadataAuthError, OnlineMetadataError) as exc:
            if not self.isInterruptionRequested():
                self.completed.emit(None, str(exc))
            return
        except Exception as exc:  # QThread boundary: never let an exception disappear silently.
            if not self.isInterruptionRequested():
                self.completed.emit(None, f"Unerwarteter Metadatenfehler: {exc}")
            return
        if not self.isInterruptionRequested():
            self.completed.emit(suggestion, "")


__all__ = ["OnlineMetadataConnectionTestThread", "OnlineMetadataMovieSearchThread"]
