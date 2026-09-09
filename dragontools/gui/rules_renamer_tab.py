# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .rules_dialog_storage import _load


class _RenamerTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui(_load("renamer_rules"))

    @staticmethod
    def _item(text: str) -> QTableWidgetItem:
        return QTableWidgetItem(str(text))

    def _init_ui(self, data: dict) -> None:
        root = QVBoxLayout(self)

        char_group = QGroupBox("Zeichenersetzungen für Zieldateinamen")
        char_layout = QVBoxLayout(char_group)
        char_layout.addWidget(QLabel(
            "Diese Regeln waren bisher fest im Renamer eingebaut. "
            "Leeres Ersatzfeld bedeutet: Zeichen entfernen."
        ))
        self.char_table = QTableWidget(0, 2)
        self.char_table.setHorizontalHeaderLabels(["Zeichen", "Ersetzung"])
        self.char_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.char_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.char_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        for row in data.get("character_replacements", []):
            self._append_char(str(row.get("character") or ""), str(row.get("replacement") or ""))
        char_layout.addWidget(self.char_table)
        buttons = QHBoxLayout()
        add_btn = QPushButton("➕ Regel hinzufügen")
        del_btn = QPushButton("➖ Auswahl entfernen")
        add_btn.clicked.connect(lambda: self._append_char("", ""))
        del_btn.clicked.connect(lambda: self._delete_selected(self.char_table))
        buttons.addWidget(add_btn)
        buttons.addWidget(del_btn)
        buttons.addStretch(1)
        char_layout.addLayout(buttons)
        root.addWidget(char_group)

        exc_group = QGroupBox("Titel-/Suchausnahmen")
        exc_layout = QVBoxLayout(exc_group)
        exc_layout.addWidget(QLabel(
            "Optional: Ein erkannter Titel kann vor der Online-Suche exakt auf einen anderen Suchnamen "
            "abgebildet werden. Groß-/Kleinschreibung und typische Satzzeichen werden beim Vergleich ignoriert."
        ))
        self.exc_table = QTableWidget(0, 2)
        self.exc_table.setHorizontalHeaderLabels(["Erkannter Titel", "Online-Suchname"])
        self.exc_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.exc_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        for row in data.get("title_exceptions", []):
            self._append_exception(str(row.get("source") or ""), str(row.get("replacement") or ""))
        exc_layout.addWidget(self.exc_table)
        exc_buttons = QHBoxLayout()
        exc_add = QPushButton("➕ Ausnahme hinzufügen")
        exc_del = QPushButton("➖ Auswahl entfernen")
        exc_add.clicked.connect(lambda: self._append_exception("", ""))
        exc_del.clicked.connect(lambda: self._delete_selected(self.exc_table))
        exc_buttons.addWidget(exc_add)
        exc_buttons.addWidget(exc_del)
        exc_buttons.addStretch(1)
        exc_layout.addLayout(exc_buttons)
        root.addWidget(exc_group)

        match_group = QGroupBox("Trefferbewertung und Fallback-Suche")
        form = QFormLayout(match_group)
        matching = dict(data.get("matching") or {})

        self.min_score = QDoubleSpinBox()
        self.min_score.setRange(0.0, 1.0)
        self.min_score.setSingleStep(0.01)
        self.min_score.setDecimals(2)
        self.min_score.setValue(float(matching.get("minimum_candidate_score", 0.60)))
        self.min_score.setToolTip("Treffer unter diesem Score werden nicht im Vorschlags-Dropdown gezeigt.")
        form.addRow("Mindestscore für Anzeige:", self.min_score)

        self.review_score = QDoubleSpinBox()
        self.review_score.setRange(0.0, 1.0)
        self.review_score.setSingleStep(0.01)
        self.review_score.setDecimals(2)
        self.review_score.setValue(float(matching.get("manual_review_below", 0.72)))
        form.addRow("Manuelle Prüfung unter:", self.review_score)

        self.auto_score = QDoubleSpinBox()
        self.auto_score.setRange(0.0, 1.0)
        self.auto_score.setSingleStep(0.01)
        self.auto_score.setDecimals(2)
        self.auto_score.setValue(float(matching.get("auto_accept_from", 0.78)))
        form.addRow("Sicher akzeptierbar ab:", self.auto_score)

        self.fuzzy = QCheckBox("Fuzzy-Fallback aktivieren")
        self.fuzzy.setChecked(bool(matching.get("fuzzy_fallback", True)))
        self.fuzzy.setToolTip(
            "Wenn die exakte Seriensuche nicht reicht, werden kontrolliert kürzere Titelvarianten versucht."
        )
        form.addRow("Fallback-Suche:", self.fuzzy)

        self.no_year = QCheckBox("Bei Bedarf zusätzlich ohne Jahr suchen")
        self.no_year.setChecked(bool(matching.get("retry_without_year", True)))
        self.no_year.setToolTip(
            "Verhindert, dass ein falsches/abweichendes Jahr im Dateinamen einen guten Treffer vollständig blockiert."
        )
        form.addRow("Jahr lockern:", self.no_year)

        self.prefix_words = QSpinBox()
        self.prefix_words.setRange(2, 8)
        self.prefix_words.setValue(int(matching.get("fuzzy_prefix_min_words", 3)))
        self.prefix_words.setToolTip("Kürzeste Wortanzahl für die kontrollierte Prefix-Suche.")
        form.addRow("Fuzzy-Prefix mindestens Wörter:", self.prefix_words)

        root.addWidget(match_group)
        root.addStretch(1)

    def _append_char(self, char: str, replacement: str) -> None:
        row = self.char_table.rowCount()
        self.char_table.insertRow(row)
        self.char_table.setItem(row, 0, self._item(char))
        self.char_table.setItem(row, 1, self._item(replacement))

    def _append_exception(self, source: str, replacement: str) -> None:
        row = self.exc_table.rowCount()
        self.exc_table.insertRow(row)
        self.exc_table.setItem(row, 0, self._item(source))
        self.exc_table.setItem(row, 1, self._item(replacement))

    @staticmethod
    def _delete_selected(table: QTableWidget) -> None:
        rows = sorted({idx.row() for idx in table.selectedIndexes()}, reverse=True)
        for row in rows:
            table.removeRow(row)

    @staticmethod
    def _cell(table: QTableWidget, row: int, col: int) -> str:
        item = table.item(row, col)
        return item.text() if item is not None else ""

    def get_data(self) -> dict:
        replacements = []
        for row in range(self.char_table.rowCount()):
            char = self._cell(self.char_table, row, 0)
            if not char:
                continue
            replacements.append({
                "character": char,
                "replacement": self._cell(self.char_table, row, 1),
            })

        exceptions = []
        for row in range(self.exc_table.rowCount()):
            source = self._cell(self.exc_table, row, 0).strip()
            replacement = self._cell(self.exc_table, row, 1).strip()
            if source and replacement:
                exceptions.append({"source": source, "replacement": replacement})

        return {
            "_schema_version": 1,
            "character_replacements": replacements,
            "title_exceptions": exceptions,
            "matching": {
                "minimum_candidate_score": self.min_score.value(),
                "manual_review_below": self.review_score.value(),
                "auto_accept_from": self.auto_score.value(),
                "fuzzy_fallback": self.fuzzy.isChecked(),
                "retry_without_year": self.no_year.isChecked(),
                "fuzzy_prefix_min_words": self.prefix_words.value(),
            },
        }
