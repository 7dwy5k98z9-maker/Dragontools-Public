# -*- coding: utf-8 -*-
"""Best-effort notification policy for conversion runs."""
from __future__ import annotations
import logging

import ntpath
from typing import Callable

from .settings_notifications import NotificationPreferences

NotificationEmitter = Callable[[str, str, str], bool]


class ConversionNotificationService:
    """Map conversion events to optional desktop notifications.

    The service intentionally owns no Qt code. Notification delivery is injected
    so failures in the desktop backend can never alter conversion results.
    """

    def __init__(self, *, settings, emit: NotificationEmitter, log: Callable | None = None) -> None:
        self._settings = settings
        self._emit = emit
        self._log = log

    def on_file_result(self, input_path: str, status: str, message: str = "") -> None:
        prefs = NotificationPreferences.from_settings(self._settings)
        if not prefs.enabled:
            return
        name = ntpath.basename(str(input_path or "").replace("/", "\\")) or "Datei"
        if status == "✅" and prefs.file_finished:
            self._safe_emit("Datei abgeschlossen", name, "info")
            return
        if status in {"❌", "⚠️"} and prefs.errors:
            detail = self._compact_message(message) or "Die Verarbeitung ist fehlgeschlagen."
            self._safe_emit("Fehler bei Datei", f"{name}\n{detail}", "error")

    def on_run_finished(self, summary: dict, *, aborted: bool = False) -> None:
        prefs = NotificationPreferences.from_settings(self._settings)
        if not prefs.enabled or aborted:
            return
        ok = int(summary.get("ok") or 0)
        errors = int(summary.get("errors") or 0)
        skipped = int(summary.get("skipped") or 0)
        move_ok = int(summary.get("move_ok") or 0)
        move_errors = int(summary.get("move_errors") or 0)

        if prefs.errors and move_errors:
            self._safe_emit(
                "Verschieben mit Fehlern",
                f"{move_errors} Fehler, {move_ok} erfolgreich verschoben.",
                "error",
            )
        if prefs.queue_finished:
            parts = [f"{ok} erfolgreich"]
            if errors:
                parts.append(f"{errors} Fehler")
            if skipped:
                parts.append(f"{skipped} übersprungen")
            if move_ok or move_errors:
                parts.append(f"Verschieben: {move_ok} OK / {move_errors} Fehler")
            level = "warning" if errors or move_errors else "info"
            self._safe_emit("Queue abgeschlossen", " · ".join(parts), level)

    def on_internal_error(self, context: str, message: str) -> None:
        prefs = NotificationPreferences.from_settings(self._settings)
        if not (prefs.enabled and prefs.errors):
            return
        detail = self._compact_message(message) or "Unbekannter Fehler"
        self._safe_emit(str(context or "Dragon Tools Fehler"), detail, "error")

    @staticmethod
    def _compact_message(message: str, *, limit: int = 220) -> str:
        text = " ".join(str(message or "").split())
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 1)].rstrip() + "…"

    def _safe_emit(self, title: str, message: str, level: str) -> None:
        try:
            self._emit(title, message, level)
        except Exception as exc:
            if self._log is not None:
                try:
                    self._log(f"Windows-Benachrichtigung konnte nicht angezeigt werden: {exc}", "warn")
                except Exception:
                    logging.getLogger(__name__).debug("Unterdrückte Best-Effort-Ausnahme in _safe_emit.", exc_info=True)
