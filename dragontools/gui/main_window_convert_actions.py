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
        """Öffnet das aktuelle GUI-Log in einem größeren separaten Fenster."""
        from PyQt6.QtWidgets import (
            QDialog, QVBoxLayout, QTextEdit, QDialogButtonBox,
        )
        from PyQt6.QtCore import Qt
        from .ui_helpers import install_persistent_window_geometry

        # Aktives ConvertWidget ermitteln um log_edit zu finden
        source_log: QTextEdit | None = None
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if w is not None and hasattr(w, "log_edit"):
                source_log = w.log_edit
                break

        dlg = QDialog(self)
        dlg.setWindowTitle("📋 Logging-Fenster")
        dlg.setMinimumSize(900, 600)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        install_persistent_window_geometry(dlg, "log_zoom_window")

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(8, 8, 8, 8)

        log_view = QTextEdit()
        log_view.setReadOnly(True)
        log_view.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        log_view.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 11px;"
        )

        # Aktuellen Inhalt übernehmen
        if source_log is not None:
            initial_text = source_log.toPlainText()
            log_view.setPlainText(initial_text)
            # Ans Ende scrollen
            sb = log_view.verticalScrollBar()
            sb.setValue(sb.maximum())

            # Neue Einträge live weiterleiten solange Fenster offen.
            # textChanged ist pyqtSignal() ohne Argument – daher kein 'line'-Parameter.
            # _prev_len trackt wieviel Text schon im Zoom-Fenster ist; nur das Delta
            # wird angehängt (kein teures setPlainText für den gesamten Log).
            _prev_len = [len(initial_text)]

            def _on_new_log() -> None:
                if not dlg.isVisible():
                    return
                current = source_log.toPlainText()
                new_part = current[_prev_len[0]:]
                _prev_len[0] = len(current)
                if not new_part:
                    return
                cursor = log_view.textCursor()
                from PyQt6.QtGui import QTextCursor
                cursor.movePosition(QTextCursor.MoveOperation.End)
                log_view.setTextCursor(cursor)
                log_view.insertPlainText(new_part)
                sb2 = log_view.verticalScrollBar()
                sb2.setValue(sb2.maximum())

            source_log.textChanged.connect(_on_new_log)
            dlg.finished.connect(lambda _: source_log.textChanged.disconnect(_on_new_log))

        layout.addWidget(log_view)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn_box.rejected.connect(dlg.reject)
        layout.addWidget(btn_box)

        dlg.show()

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
