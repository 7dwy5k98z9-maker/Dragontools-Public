# -*- coding: utf-8 -*-
"""
dragontools/gui/profile_manager_dialog.py

Profilverwaltungsdialog – ausgelagert aus main_window._open_profile_manager().

Vorher: ~100 Zeilen inline-UI-Code direkt in einer Menüaktion des MainWindow.
Jetzt:  eigenstaendige, wiederverwendbare Dialog-Klasse.

Benutzung
---------
    from .profile_manager_dialog import open_profile_manager
    open_profile_manager(tabs_widget, parent=self)

Oder direkt über den Dialog:
    ProfileManagerDialog(pm_widget, parent=self).exec()
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget,
    QListWidgetItem, QPushButton, QLabel, QDialogButtonBox,
    QMessageBox, QTabWidget,
)

from ..core.audit_log import append_audit_event
from .ui_helpers import install_persistent_window_geometry


class ProfileManagerDialog(QDialog):
    """Zeigt benutzerdefinierte Profile des übergebenen ConvertWidget-Tabs an.

    Parameters
    ----------
    pm_widget:
        Ein ConvertWidget (oder kompatibles Widget) das ``profile_manager``
        sowie die öffentlichen Methoden ``apply_profile(p)`` und ``log_message(...)`` besitzt.
    parent:
        Eltern-Widget (MainWindow).
    """

    def __init__(self, pm_widget, parent=None):
        super().__init__(parent)
        self._pm_widget = pm_widget
        self._pm = pm_widget.profile_manager

        self.setWindowTitle("Profilverwaltung")
        self.setMinimumWidth(480)
        self._build_ui()
        install_persistent_window_geometry(self, "profile_manager_dialog")

    def _build_ui(self) -> None:
        v = QVBoxLayout(self)
        v.addWidget(QLabel(
            "<b>Eigene Profile</b>  "
            "<small style='color:#666'>(Standard-Profile werden nicht angezeigt)</small>"
        ))

        self._lst = QListWidget()
        self._refresh()
        v.addWidget(self._lst)

        btn_row = QHBoxLayout()
        load_btn = QPushButton("📂 Laden")
        del_btn = QPushButton("🗑️ Löschen")
        del_btn.setStyleSheet("color:#c0392b;")
        btn_row.addWidget(load_btn)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()
        v.addLayout(btn_row)

        close_btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_btn.rejected.connect(self.reject)
        v.addWidget(close_btn)

        load_btn.clicked.connect(self._do_load)
        del_btn.clicked.connect(self._do_delete)
        self._lst.itemDoubleClicked.connect(lambda _: self._do_load())

    def _refresh(self) -> None:
        self._lst.clear()
        pm = self._pm
        for display, key in pm.user_display_choices():
            item = QListWidgetItem(display)
            item.setData(0x100, key)  # UserRole
            self._lst.addItem(item)
        if self._lst.count() == 0:
            self._lst.addItem(QListWidgetItem("(Keine eigenen Profile vorhanden)"))

    def _do_load(self) -> None:
        item = self._lst.currentItem()
        if not item:
            return
        key = item.data(0x100)
        if not key:
            return
        p = self._pm.get(key)
        if p:
            display = self._pm.profile_display_name(key, p)
            self._pm_widget.apply_profile(p)
            self._pm_widget.log_message(f"📂 Profil '{display}' geladen.")
            append_audit_event("Profil geladen", f"{display} | Schlüssel: {key}")
        self.accept()

    def _do_delete(self) -> None:
        item = self._lst.currentItem()
        if not item:
            return
        key = item.data(0x100)
        if not key:
            return
        display = self._pm.profile_display_name(key, self._pm.get(key))
        res = QMessageBox.question(
            self, "Löschen",
            f"Profil '{display}' wirklich löschen?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if res == QMessageBox.StandardButton.Yes:
            self._pm.delete(key)
            self._pm_widget.log_message(f"🗑 Profil '{display}' gelöscht.")
            append_audit_event("Profil gelöscht", f"{display} | Schlüssel: {key}")
            self._refresh()


# ---------------------------------------------------------------------------
# Convenience-Funktion (direkt aus MainWindow aufzurufen)
# ---------------------------------------------------------------------------

def open_profile_manager(tabs: QTabWidget, parent=None) -> None:
    """Öffnet den Profilverwaltungsdialog für den aktuell aktiven Tab.

    Sucht den ersten Tab mit ``profile_manager``-Attribut.  Bevorzugt den
    gerade sichtbaren Tab.  Zeigt einen Hinweis-Dialog wenn kein passender
    Tab offen ist.
    """
    tabs_with_pm = [
        tabs.widget(i)
        for i in range(tabs.count())
        if hasattr(tabs.widget(i), "profile_manager")
    ]

    if not tabs_with_pm:
        QMessageBox.information(
            parent, "Profile",
            "Bitte zuerst einen Konverter-Tab öffnen."
        )
        return

    cur = tabs.currentWidget()
    pm_widget = cur if hasattr(cur, "profile_manager") else tabs_with_pm[0]
    ProfileManagerDialog(pm_widget, parent=parent).exec()
