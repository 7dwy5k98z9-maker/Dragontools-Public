# -*- coding: utf-8 -*-
"""
dragontools/gui/rules_dialog.py
Regeln-Editor: Serien, Audio, Untertitel und Flags.
"""
from __future__ import annotations

from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QMessageBox, QTabWidget, QVBoxLayout

from .rules_audio_tab import _AudioTab
from .rules_dialog_storage import _rules_dir, _save
from .rules_flags_tab import _FlagsTab
from .rules_renamer_tab import _RenamerTab
from .rules_series_tab import _SeriesTab
from .rules_subtitle_tab import _SubtitleTab
from .ui_helpers import install_persistent_window_geometry
from ..core.settings import APP_VERSION


class RulesDialog(QDialog):
    TAB_DEFS = (
        ("series", "🔍 Serien-Erkennung", _SeriesTab),
        ("renamer", "🎞 Renamer-Regeln", _RenamerTab),
        ("audio", "🔊 Audio-Regeln", _AudioTab),
        ("subtitles", "💬 Untertitel-Regeln", _SubtitleTab),
        ("flags", "🏷️ Untertitel-Flags", _FlagsTab),
    )

    def __init__(
        self,
        parent=None,
        *,
        visible_tabs: tuple[str, ...] | None = None,
        initial_tab: str | None = None,
        window_title: str | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"Regeln bearbeiten – Dragon Tools V{APP_VERSION}")
        self._visible_tabs = tuple(
            key for key in (visible_tabs or tuple(key for key, _, _ in self.TAB_DEFS))
            if any(key == tab_key for tab_key, _, _ in self.TAB_DEFS)
        )
        self._tab_index_by_key: dict[str, int] = {}
        if window_title:
            self.setWindowTitle(window_title)
        self.setMinimumSize(720, 640)
        root = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self._s = self._r = self._a = self._su = self._f = None
        for key, label, widget_cls in self.TAB_DEFS:
            if key not in self._visible_tabs:
                continue
            widget = widget_cls()
            if key == "series":
                self._s = widget
            elif key == "renamer":
                self._r = widget
            elif key == "audio":
                self._a = widget
            elif key == "subtitles":
                self._su = widget
            elif key == "flags":
                self._f = widget
            self._tab_index_by_key[key] = self.tabs.addTab(widget, label)
        root.addWidget(self.tabs)
        if initial_tab in self._tab_index_by_key:
            self.tabs.setCurrentIndex(self._tab_index_by_key[initial_tab])
        if len(self._tab_index_by_key) == 1 and not window_title:
            only_key = next(iter(self._tab_index_by_key))
            only_label = next(label for key, label, _ in self.TAB_DEFS if key == only_key)
            self.setWindowTitle(f"{only_label} – Dragon Tools V{APP_VERSION}")
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Save).setText("💾 Speichern")
        bb.accepted.connect(self._save); bb.rejected.connect(self.reject)
        root.addWidget(bb)
        geometry_scope = "all" if len(self._visible_tabs) != 1 else self._visible_tabs[0]
        install_persistent_window_geometry(self, f"rules_dialog/{geometry_scope}")

    def _save(self):
        if self._s is not None:
            _save("move_rules", self._s.get_data())
        if self._r is not None:
            _save("renamer_rules", self._r.get_data())
        if self._a is not None:
            _save("audio_rules", self._a.get_data())
        if self._su is not None:
            _save("subtitle_rules", self._su.get_data())
        QMessageBox.information(self, "Gespeichert",
            f"Regeln gespeichert:\n{_rules_dir()}")
        self.accept()
