# -*- coding: utf-8 -*-
"""Manual SQL tab construction for the media-library dialog."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


def build_sql_tab(owner, actions) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    warning = QLabel(
        "Manuelle SQL-Bearbeitung ist für gezielte Korrekturen gedacht. Vor Änderungen erstellt "
        "Dragon Tools automatisch eine Sicherung der eigenen Mediathek-Datenbank."
    )
    warning.setWordWrap(True)
    layout.addWidget(warning)

    _build_saved_sql_bar(owner, actions, layout)
    owner.sql_edit = QTextEdit()
    owner.sql_edit.setPlaceholderText("SELECT * FROM media_items LIMIT 50")
    owner.sql_edit.setPlainText(
        "SELECT item_type, title, series_title, season, episode, year, path "
        "FROM media_items LIMIT 50"
    )
    layout.addWidget(owner.sql_edit, 1)
    _build_sql_action_bar(actions, layout)

    owner.sql_result_table = QTableWidget(0, 0)
    owner.sql_result_table.horizontalHeader().setSectionResizeMode(
        QHeaderView.ResizeMode.ResizeToContents
    )
    layout.addWidget(owner.sql_result_table, 2)
    return page


def _build_saved_sql_bar(owner, actions, layout: QVBoxLayout) -> None:
    bar = QHBoxLayout()
    bar.addWidget(QLabel("Gespeicherte SQL-Abfrage:"))
    owner.saved_sql_combo = QComboBox()
    owner.saved_sql_combo.setMinimumWidth(260)
    bar.addWidget(owner.saved_sql_combo, 1)
    for label, callback in (
        ("Laden", actions.load_saved_sql),
        ("Speichern", actions.save_current_sql),
        ("Löschen", actions.delete_saved_sql),
    ):
        button = QPushButton(label)
        button.clicked.connect(callback)
        bar.addWidget(button)
    layout.addLayout(bar)


def _build_sql_action_bar(actions, layout: QVBoxLayout) -> None:
    bar = QHBoxLayout()
    help_btn = QPushButton("SQL-Hilfe / Tabellen & Attribute")
    help_btn.setToolTip(
        "Zeigt verfügbare SQL-Befehle, alle Tabellen, Spalten und Beispielabfragen."
    )
    help_btn.clicked.connect(actions.show_sql_help)
    export_help_btn = QPushButton("Schema-Info exportieren")
    export_help_btn.clicked.connect(actions.export_sql_help)
    run_btn = QPushButton("SQL ausführen")
    run_btn.clicked.connect(actions.run_sql)
    bar.addWidget(help_btn)
    bar.addWidget(export_help_btn)
    bar.addStretch(1)
    bar.addWidget(run_btn)
    layout.addLayout(bar)
