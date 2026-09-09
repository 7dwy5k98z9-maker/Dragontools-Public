# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6.QtWidgets import QApplication, QMessageBox

from .styles import STYLE_DARK, STYLE_LIGHT


class MainWindowProfileActionsMixin:
    def _open_profile_manager(self) -> None:
        """Profilverwaltung: eigene Profile anzeigen, laden, löschen."""
        from .profile_manager_dialog import open_profile_manager
        open_profile_manager(self.tabs, parent=self)

    def _reset_defaults(self):
        res = QMessageBox.question(
            self, "Standardwerte",
            "Alle Einstellungen zurücksetzen?\n\n"
            "Gespeicherte Pfade, Profile und Fenstergrößen\n"
            "werden auf die Standardwerte zurückgesetzt.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if res == QMessageBox.StandardButton.Yes:
            self._settings.clear()
            self._settings.sync()
            # Standard-Film-Profil auf alle aktiven Konverter-Tabs anwenden
            self._apply_default_profile()
            QMessageBox.information(self, "Standardwerte wiederhergestellt",
                "Einstellungen zurückgesetzt.\n"
                "Standard-Filmprofil wurde geladen.")

    def _toggle_dark(self, on: bool):
        self._dark = on
        app = QApplication.instance()
        if app:
            app.setStyleSheet(STYLE_DARK if on else STYLE_LIGHT)

    def _apply_default_profile(self) -> None:
        """Lädt das Standard-Filmprofil auf alle aktiven Konverter-Tabs."""
        from ..core.profile_manager import _DEFAULTS
        # Encoder-spezifisches Film-Profil wählen:
        # Priorität: nvenc > qsv > amf > cpu (passend zur erkannten GPU)
        try:
            from ..core.gpu_detection import best_encoder
            enc = best_encoder()
        except Exception:
            enc = "cpu"
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if hasattr(w, "reset_encoder_defaults"):
                w.reset_encoder_defaults()
            if hasattr(w, "apply_profile"):
                codec = getattr(w, "default_codec", "h265")
                if codec == "h265":
                    profile_key = f"film_{enc}"
                    if profile_key not in _DEFAULTS:
                        profile_key = "film_cpu"
                elif codec == "h264":
                    profile_key = "film_h264"
                elif codec == "av1":
                    profile_key = "film_av1"
                else:
                    profile_key = "film_cpu"
                p = _DEFAULTS[profile_key]
                w.apply_profile(p)
                if hasattr(w, "save_encoder_settings"):
                    w.save_encoder_settings()
