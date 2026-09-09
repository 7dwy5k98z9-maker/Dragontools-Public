# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QGridLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from ..core.lang_codes import LANGUAGE_CHOICES, canonical_lang, lang_display, normalize_language_priority


class _LanguagePriorityEditor(QWidget):
    def __init__(
        self,
        *,
        priority,
        max_languages: int = 1,
        tracks_per_language: int = 1,
        fallback_policy: str = "keep_none",
        fallback_options: list[tuple[str, str]],
        max_label: str,
        tracks_label: str,
        parent=None,
    ):
        super().__init__(parent)
        self._fallback_options = list(fallback_options)
        self._init_ui(
            priority=priority,
            max_languages=max_languages,
            tracks_per_language=tracks_per_language,
            fallback_policy=fallback_policy,
            max_label=max_label,
            tracks_label=tracks_label,
        )

    def _init_ui(
        self,
        *,
        priority,
        max_languages: int,
        tracks_per_language: int,
        fallback_policy: str,
        max_label: str,
        tracks_label: str,
    ):
        v = QVBoxLayout(self)

        add_row = QHBoxLayout()
        self.add_combo = QComboBox()
        self.add_combo.setEditable(True)
        for code, name in LANGUAGE_CHOICES:
            self.add_combo.addItem(f"{name} ({code})", code)
        add_btn = QPushButton("Hinzufügen")
        add_btn.clicked.connect(self._add_selected)
        add_row.addWidget(self.add_combo, 1)
        add_row.addWidget(add_btn)
        v.addLayout(add_row)

        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setMinimumHeight(92)
        self.list.setMaximumHeight(130)
        for code in normalize_language_priority(priority):
            self._add_language(code)
        v.addWidget(self.list)

        btn_row = QHBoxLayout()
        up_btn = QPushButton("Hoch")
        down_btn = QPushButton("Runter")
        del_btn = QPushButton("Entfernen")
        up_btn.clicked.connect(lambda: self._move_current(-1))
        down_btn.clicked.connect(lambda: self._move_current(1))
        del_btn.clicked.connect(self._remove_current)
        btn_row.addWidget(up_btn)
        btn_row.addWidget(down_btn)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()
        v.addLayout(btn_row)

        grid = QGridLayout()
        grid.addWidget(QLabel(max_label), 0, 0)
        self.max_languages = QSpinBox()
        self.max_languages.setRange(0, 32)
        self.max_languages.setSpecialValueText("Alle")
        self.max_languages.setValue(max(0, int(max_languages or 0)))
        grid.addWidget(self.max_languages, 0, 1)

        grid.addWidget(QLabel(tracks_label), 1, 0)
        self.tracks_per_language = QSpinBox()
        self.tracks_per_language.setRange(0, 32)
        self.tracks_per_language.setSpecialValueText("Alle")
        self.tracks_per_language.setValue(max(0, int(tracks_per_language or 0)))
        grid.addWidget(self.tracks_per_language, 1, 1)

        grid.addWidget(QLabel("Wenn keine Sprache gefunden wird:"), 2, 0)
        self.fallback_policy = QComboBox()
        for value, label in self._fallback_options:
            self.fallback_policy.addItem(label, value)
        idx = self.fallback_policy.findData(fallback_policy)
        self.fallback_policy.setCurrentIndex(idx if idx >= 0 else 0)
        grid.addWidget(self.fallback_policy, 2, 1)
        v.addLayout(grid)

    def _item_text(self, code: str) -> str:
        return f"{lang_display(code)} ({code})"

    def _add_language(self, raw_code) -> None:
        code = canonical_lang(str(raw_code))
        if not code:
            return
        existing = set(self.priority())
        if code in existing:
            return
        item = QListWidgetItem(self._item_text(code))
        item.setData(Qt.ItemDataRole.UserRole, code)
        self.list.addItem(item)

    def _add_selected(self) -> None:
        text = self.add_combo.currentText()
        idx = self.add_combo.currentIndex()
        if idx >= 0 and text == self.add_combo.itemText(idx):
            self._add_language(self.add_combo.itemData(idx) or text)
        else:
            self._add_language(text)

    def _remove_current(self) -> None:
        row = self.list.currentRow()
        if row >= 0:
            self.list.takeItem(row)

    def _move_current(self, delta: int) -> None:
        row = self.list.currentRow()
        new_row = row + delta
        if row < 0 or new_row < 0 or new_row >= self.list.count():
            return
        item = self.list.takeItem(row)
        self.list.insertItem(new_row, item)
        self.list.setCurrentRow(new_row)

    def priority(self) -> list[str]:
        values: list[str] = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            values.append(str(item.data(Qt.ItemDataRole.UserRole) or item.text()))
        return normalize_language_priority(values)

    def data(self) -> dict:
        return {
            "language_priority": self.priority(),
            "max_languages": self.max_languages.value(),
            "tracks_per_language": self.tracks_per_language.value(),
            "fallback_if_no_priority_match": self.fallback_policy.currentData(),
        }
