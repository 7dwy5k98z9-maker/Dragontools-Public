# -*- coding: utf-8 -*-
"""Path-mapping tab construction for the media-library dialog."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)


def build_mapping_tab(owner, actions) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    hint = QLabel(
        "Pfad-Mapping übersetzt Jellyfin-Pfade in deine Windows-/NAS-Pfade, z. B. /Anime -> "
        "\\\\Media-Share\\video\\Serien\\Anime. Die Einträge sind frei anpassbar."
    )
    hint.setWordWrap(True)
    layout.addWidget(hint)

    owner.mapping_table = QTableWidget(0, 3)
    owner.mapping_table.setHorizontalHeaderLabels(
        ["Bereich", "Jellyfin-Pfad", "DragonTools-Pfad"]
    )
    header = owner.mapping_table.horizontalHeader()
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
    header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
    layout.addWidget(owner.mapping_table, 1)

    bar = QHBoxLayout()
    add_btn = QPushButton("Zeile hinzufügen")
    add_btn.clicked.connect(lambda: actions.add_mapping_row(None))
    remove_btn = QPushButton("Auswahl entfernen")
    remove_btn.clicked.connect(actions.remove_mapping_rows)
    defaults_btn = QPushButton("Aus Speicherpfaden ableiten")
    defaults_btn.clicked.connect(actions.fill_mapping_from_storage_paths)
    save_btn = QPushButton("Mapping speichern")
    save_btn.clicked.connect(actions.save_mappings)
    bar.addWidget(add_btn)
    bar.addWidget(remove_btn)
    bar.addWidget(defaults_btn)
    bar.addStretch(1)
    bar.addWidget(save_btn)
    layout.addLayout(bar)
    return page
