# -*- coding: utf-8 -*-
"""Search tab construction for the media-library dialog."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from .media_library_dialog_options import (
    SEARCH_ITEM_TYPES,
    SEARCH_MODES,
    SEARCH_OPTIONS,
    SEARCH_SCOPES,
)


def build_search_tab(owner, actions) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    _build_saved_search_bar(owner, actions, layout)
    _build_search_controls(owner, actions, layout)

    owner.search_result_label = QLabel("0 Treffer")
    layout.addWidget(owner.search_result_label)

    owner.search_table = QTableWidget(0, 16)
    owner.search_table.setHorizontalHeaderLabels(
        [
            "Typ", "Titel", "Serie", "S", "E", "Jahr", "Video", "Bild",
            "Audio", "Untertitel", "NFO", "NFO-Prüfung", "Dauer", "Größe",
            "Abweichung", "Pfad",
        ]
    )
    header = owner.search_table.horizontalHeader()
    for idx in range(15):
        header.setSectionResizeMode(idx, QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(15, QHeaderView.ResizeMode.Stretch)
    owner.search_table.setSortingEnabled(True)
    layout.addWidget(owner.search_table, 1)
    update_search_options(owner)
    return page


def update_search_options(owner, _index: int | None = None) -> None:
    mode = owner.search_mode_combo.currentData() or "all"
    options = SEARCH_OPTIONS.get(str(mode), SEARCH_OPTIONS["all"])
    previous = owner.search_option_combo.currentData()
    owner.search_option_combo.blockSignals(True)
    owner.search_option_combo.clear()
    for label, key in options:
        owner.search_option_combo.addItem(label, key)
    if previous is not None:
        idx = owner.search_option_combo.findData(previous)
        if idx >= 0:
            owner.search_option_combo.setCurrentIndex(idx)
    owner.search_option_combo.setEnabled(len(options) > 1)
    owner.search_option_combo.blockSignals(False)


def _build_saved_search_bar(owner, actions, layout: QVBoxLayout) -> None:
    bar = QHBoxLayout()
    bar.addWidget(QLabel("Gespeicherte Suche:"))
    owner.saved_search_combo = QComboBox()
    owner.saved_search_combo.setMinimumWidth(240)
    bar.addWidget(owner.saved_search_combo, 1)
    for label, callback in (
        ("Laden", actions.load_saved_search),
        ("Aktuelle speichern", actions.save_current_search),
        ("Löschen", actions.delete_saved_search),
    ):
        button = QPushButton(label)
        button.clicked.connect(callback)
        bar.addWidget(button)
    layout.addLayout(bar)


def _build_search_controls(owner, actions, layout: QVBoxLayout) -> None:
    top = QGridLayout()
    owner.search_mode_combo = QComboBox()
    for label, key in SEARCH_MODES:
        owner.search_mode_combo.addItem(label, key)
    owner.search_mode_combo.currentIndexChanged.connect(owner.update_search_options)

    owner.search_option_combo = QComboBox()
    owner.search_scope_combo = QComboBox()
    for label, key in SEARCH_SCOPES:
        owner.search_scope_combo.addItem(label, key)
    owner.search_type_combo = QComboBox()
    for label, key in SEARCH_ITEM_TYPES:
        owner.search_type_combo.addItem(label, key)
    owner.search_text_edit = QLineEdit()
    owner.search_text_edit.setPlaceholderText("Optional: Titel, Serie, Dateiname oder Pfad")
    owner.search_text_edit.returnPressed.connect(actions.run_search)
    search_btn = QPushButton("Suchen")
    search_btn.clicked.connect(actions.run_search)
    export_btn = QPushButton("Treffer als CSV")
    export_btn.clicked.connect(actions.export_search_csv)

    top.addWidget(QLabel("Abfrage:"), 0, 0)
    top.addWidget(owner.search_mode_combo, 0, 1)
    top.addWidget(QLabel("Kriterium:"), 0, 2)
    top.addWidget(owner.search_option_combo, 0, 3)
    top.addWidget(QLabel("Bereich:"), 1, 0)
    top.addWidget(owner.search_scope_combo, 1, 1)
    top.addWidget(QLabel("Typ:"), 1, 2)
    top.addWidget(owner.search_type_combo, 1, 3)
    top.addWidget(owner.search_text_edit, 2, 0, 1, 4)
    top.addWidget(search_btn, 2, 4)
    top.addWidget(export_btn, 2, 5)
    top.setColumnStretch(3, 1)
    layout.addLayout(top)
