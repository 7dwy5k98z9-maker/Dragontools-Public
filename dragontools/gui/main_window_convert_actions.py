# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox


class MainWindowConvertActionsMixin:
    def _open_convert_queue(self):
        idx = self.tabs.currentIndex()
        if idx < 0:
            QMessageBox.information(self, "Warteschlange", "Kein Convert-Bereich aktiv.")
            return

        key = self.tabs.tabBar().tabData(idx)
        if key not in ("h265", "h264", "av1"):
            QMessageBox.information(
                self,
                "Warteschlange",
                "Die Warteschlange kann nur aus einem aktiven Convert-Tab geöffnet werden.",
            )
            return

        self._ensure_tab_loaded(idx)
        widget = self.tabs.widget(idx)
        if widget is None or widget.__class__.__name__ != "ConvertWidget":
            QMessageBox.warning(
                self,
                "Warteschlange",
                "Der Convert-Bereich konnte nicht geladen werden.",
            )
            return

        widget.open_queue_window()

    def _active_convert_widget(self):
        idx = self.tabs.currentIndex()
        if idx < 0:
            return None
        key = self.tabs.tabBar().tabData(idx)
        if key not in ("h265", "h264", "av1"):
            return None
        self._ensure_tab_loaded(idx)
        widget = self.tabs.widget(idx)
        if widget is None or widget.__class__.__name__ != "ConvertWidget":
            return None
        return widget

    def _show_active_queue_rule_test(self):
        widget = self._active_convert_widget()
        if widget is None:
            QMessageBox.information(
                self,
                "Regel-/Profil-Simulator",
                "Der Queue-Simulator kann nur aus einem aktiven Convert-Tab geöffnet werden.",
            )
            return
        widget.show_batch_rule_test()

    def _show_running_job_diagnostics(self):
        widget = self._active_convert_widget()
        if widget is None:
            QMessageBox.information(
                self,
                "Laufender Job",
                "Die Job-Diagnose kann nur aus einem aktiven Convert-Tab geöffnet werden.",
            )
            return
        report = widget.running_job_diagnostics()
        QMessageBox.information(
            self,
            "Laufender Job - Diagnose",
            report or "Kein Diagnosebericht verfügbar.",
        )

    def _open_log_zoom_window(self) -> None:
        """Öffnet das Log des aktiven Tabs; sonst das erste verfügbare Log."""
        from .log_zoom_window import open_log_zoom_window

        current = self.tabs.widget(self.tabs.currentIndex())
        source = getattr(current, "log_edit", None) if current is not None else None
        if source is None:
            for index in range(self.tabs.count()):
                widget = self.tabs.widget(index)
                source = getattr(widget, "log_edit", None) if widget is not None else None
                if source is not None:
                    break
        open_log_zoom_window(self, source)

    def _delete_selected_file(self):
        """Entfernt die markierte Datei aus dem aktiven Konverter-Widget."""
        idx = self.tabs.currentIndex()
        if idx < 0:
            return
    
        w = self.tabs.widget(idx)
        if w is None:
            return
    
        # Nur Widgets unterstützen, die den korrekten Remove-Pfad haben
        if hasattr(w, "remove_selected_files"):
            w.remove_selected_files()
