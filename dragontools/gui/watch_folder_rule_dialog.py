# -*- coding: utf-8 -*-
"""Editor dialog for one Watch-Folder rule."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLineEdit, QMessageBox, QPushButton, QVBoxLayout,
)

from ..core.profile_manager import ProfileManager
from ..core.watch_folder import WatchFolderRule


class WatchFolderRuleDialog(QDialog):
    def __init__(self, parent=None, *, rule: WatchFolderRule | None = None) -> None:
        super().__init__(parent)
        self._rule = rule
        self.setWindowTitle("Watch-Folder bearbeiten" if rule else "Watch-Folder hinzufügen")
        self.setMinimumWidth(620)
        root = QVBoxLayout(self)
        form = QFormLayout()
        root.addLayout(form)

        self.name_edit = QLineEdit(rule.name if rule else "")
        form.addRow("Name:", self.name_edit)

        path_row = QHBoxLayout()
        self.path_edit = QLineEdit(rule.path if rule else "")
        path_row.addWidget(self.path_edit, 1)
        browse = QPushButton("…")
        browse.setFixedWidth(32)
        browse.clicked.connect(self._browse)
        path_row.addWidget(browse)
        form.addRow("Ordner:", path_row)

        self.enabled_cb = QCheckBox("Regel aktiv")
        self.enabled_cb.setChecked(rule.enabled if rule else True)
        form.addRow("", self.enabled_cb)

        self.recursive_cb = QCheckBox("Unterordner überwachen")
        self.recursive_cb.setChecked(rule.recursive if rule else True)
        form.addRow("", self.recursive_cb)

        self.codec_combo = QComboBox()
        self.codec_combo.addItem("H.265 / DV / HDR10+", "h265")
        self.codec_combo.addItem("H.264", "h264")
        self.codec_combo.addItem("AV1", "av1")
        wanted_codec = rule.codec if rule else "h265"
        idx = self.codec_combo.findData(wanted_codec)
        self.codec_combo.setCurrentIndex(max(0, idx))
        self.codec_combo.currentIndexChanged.connect(self._reload_profiles)
        form.addRow("Converter:", self.codec_combo)

        self.profile_combo = QComboBox()
        form.addRow("Encoder-Profil:", self.profile_combo)
        self._reload_profiles(rule.profile_key if rule else "")

        self.auto_start_cb = QCheckBox("Verarbeitung automatisch starten, wenn der Converter frei ist")
        self.auto_start_cb.setChecked(rule.auto_start if rule else True)
        self.auto_start_cb.setToolTip(
            "Bei aktivem Verschieben bleibt der automatische Start aus Sicherheitsgründen stehen, "
            "weil der vorhandene Preflight eine Benutzerentscheidung verlangt."
        )
        form.addRow("", self.auto_start_cb)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept_validated)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Watch-Folder wählen", self.path_edit.text())
        if folder:
            self.path_edit.setText(folder)
            if not self.name_edit.text().strip():
                self.name_edit.setText(Path(folder).name)

    def _reload_profiles(self, preferred: str | None = None) -> None:
        previous = preferred if preferred is not None else self.profile_combo.currentData()
        codec = str(self.codec_combo.currentData() or "h265")
        self.profile_combo.clear()
        self.profile_combo.addItem("Globales Converter-Profil verwenden", "")
        manager = ProfileManager(Path.home() / "Documents" / "DragonTools" / f"{codec}_profiles.json")
        for key, profile in sorted(manager.data.items()):
            profile_codec = str(profile.get("codec") or codec).strip().lower()
            if profile_codec != codec:
                continue
            self.profile_combo.addItem(manager.profile_display_name(key, profile), key)
        idx = self.profile_combo.findData(str(previous or ""))
        self.profile_combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _accept_validated(self) -> None:
        if not self.path_edit.text().strip():
            QMessageBox.warning(self, "Watch-Folder", "Bitte einen zu überwachenden Ordner auswählen.")
            return
        self.accept()

    def rule(self) -> WatchFolderRule:
        path = self.path_edit.text().strip()
        name = self.name_edit.text().strip() or Path(path).name or path
        return WatchFolderRule.from_mapping({
            "rule_id": self._rule.rule_id if self._rule else uuid4().hex,
            "name": name,
            "path": path,
            "recursive": self.recursive_cb.isChecked(),
            "codec": self.codec_combo.currentData() or "h265",
            "profile_key": self.profile_combo.currentData() or "",
            "auto_start": self.auto_start_cb.isChecked(),
            "enabled": self.enabled_cb.isChecked(),
        })
