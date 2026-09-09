# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSpinBox,
    QTextEdit, QVBoxLayout, QWidget,
)


class _FlagsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent); self._init_ui()

    def _init_ui(self):
        v = QVBoxLayout(self)
        v.addWidget(QLabel("<b>Forced-Flag und Sprach-Tag direkt auf MKV-Dateien setzen</b><br>Nutzt mkvpropedit."))
        self.file_list = QListWidget()
        br = QHBoxLayout()
        ab = QPushButton("➕ MKV-Dateien"); ab.clicked.connect(self._add)
        cb = QPushButton("🗑️ Leeren"); cb.clicked.connect(self.file_list.clear)
        br.addWidget(ab); br.addWidget(cb)
        v.addWidget(self.file_list); v.addLayout(br)
        cfg = QGroupBox("Einstellungen"); cg = QGridLayout(cfg)
        cg.addWidget(QLabel("Track-Index:"), 0, 0)
        self.idx = QSpinBox(); self.idx.setRange(0,99); cg.addWidget(self.idx, 0, 1)
        cg.addWidget(QLabel("Sprache:"), 1, 0)
        self.lang = QLineEdit("de"); cg.addWidget(self.lang, 1, 1)
        self.forced = QCheckBox("Forced-Flag setzen"); cg.addWidget(self.forced, 2, 0, 1, 2)
        v.addWidget(cfg)
        sb = QPushButton("▶ Flags setzen"); sb.clicked.connect(self._apply); v.addWidget(sb)
        self.log = QTextEdit(); self.log.setReadOnly(True); v.addWidget(self.log)

    def _add(self):
        files,_ = QFileDialog.getOpenFileNames(self,"MKV wählen","","MKV (*.mkv);;Alle (*)")
        for f in files:
            item = QListWidgetItem(Path(f).name); item.setData(Qt.ItemDataRole.UserRole, f)
            self.file_list.addItem(item)

    def _apply(self):
        from ..subtitle.tagger import set_track_language, set_forced_flag
        files = [self.file_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.file_list.count())]
        if not files: return
        for path in files:
            self.log.append(f"▶ {Path(path).name}")
            ok1 = set_track_language(path, self.idx.value(), self.lang.text().strip() or "de")
            self.log.append(f"  Sprache: {'✅' if ok1 else '❌'}")
            if self.forced.isChecked():
                ok2 = set_forced_flag(path, self.idx.value(), True)
                self.log.append(f"  Forced:  {'✅' if ok2 else '❌'}")


# ===========================================================================
# Haupt-Dialog
# ===========================================================================
