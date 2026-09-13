# -*- coding: utf-8 -*-
"""Status/import tab construction for the media-library dialog."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


def build_status_tab(owner, actions) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    _build_database_group(owner, actions, layout)
    _build_import_group(owner, actions, layout)

    owner.stats_label = QLabel("")
    owner.stats_label.setWordWrap(True)
    owner.stats_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    layout.addWidget(owner.stats_label)
    layout.addStretch(1)
    return page


def _build_database_group(owner, actions, layout: QVBoxLayout) -> None:
    group = QGroupBox("Datenbank")
    grid = QGridLayout(group)
    owner.enabled_cb = QCheckBox("Mediathek-Datenbank verwenden")
    owner.preflight_cb = QCheckBox("Preflight bevorzugt aus der Datenbank auflösen")
    owner.analyze_import_cb = QCheckBox(
        "Beim Import vorhandene Videodateien direkt analysieren (langsamer)"
    )
    owner.enabled_cb.toggled.connect(actions.update_enabled_state)
    grid.addWidget(owner.enabled_cb, 0, 0, 1, 3)
    grid.addWidget(owner.preflight_cb, 1, 0, 1, 3)
    grid.addWidget(owner.analyze_import_cb, 2, 0, 1, 3)

    owner.db_path_edit = QLineEdit()
    db_browse = QPushButton("...")
    db_browse.setFixedWidth(36)
    db_browse.clicked.connect(actions.browse_db_path)
    grid.addWidget(QLabel("DragonTools-DB:"), 3, 0)
    grid.addWidget(owner.db_path_edit, 3, 1)
    grid.addWidget(db_browse, 3, 2)
    layout.addWidget(group)


def _build_import_group(owner, actions, layout: QVBoxLayout) -> None:
    group = QGroupBox("Import / Export")
    grid = QGridLayout(group)
    owner.jellyfin_path_edit = QLineEdit()
    jf_browse = QPushButton("...")
    jf_browse.setFixedWidth(36)
    jf_browse.clicked.connect(actions.browse_jellyfin_db)
    grid.addWidget(QLabel("Jellyfin-DB:"), 0, 0)
    grid.addWidget(owner.jellyfin_path_edit, 0, 1)
    grid.addWidget(jf_browse, 0, 2)

    buttons = _create_action_buttons(owner, actions)
    grid.addWidget(buttons["new"], 1, 0)
    grid.addWidget(buttons["import"], 1, 1)
    grid.addWidget(buttons["export"], 1, 2)
    grid.addWidget(buttons["scan"], 2, 0, 1, 2)
    grid.addWidget(buttons["scan_abort"], 2, 2)
    grid.addWidget(buttons["nfo_light"], 3, 0)
    grid.addWidget(buttons["nfo_full"], 3, 1)
    grid.addWidget(buttons["nfo_abort"], 3, 2)
    grid.addWidget(buttons["export_csv"], 4, 0, 1, 3)
    grid.addWidget(buttons["normalize"], 5, 0, 1, 3)
    grid.addWidget(buttons["cleanup"], 6, 0, 1, 3)
    grid.addWidget(buttons["save"], 7, 0, 1, 3)

    owner.scan_progress = QProgressBar()
    owner.scan_progress.setRange(0, 100)
    owner.scan_progress.setValue(0)
    owner.scan_status_label = QLabel(
        "Speicherpfad-Scan nutzt die hinterlegten Film-, Anime- und TV-Ordner. "
        "MediaInfo ist die primäre Analysequelle; ffprobe ergänzt fehlende Werte."
    )
    owner.scan_status_label.setWordWrap(True)
    grid.addWidget(owner.scan_progress, 8, 0, 1, 3)
    grid.addWidget(owner.scan_status_label, 9, 0, 1, 3)

    owner.nfo_progress = QProgressBar()
    owner.nfo_progress.setRange(0, 100)
    owner.nfo_progress.setValue(0)
    owner.nfo_status_label = QLabel(
        "NFO-Lightscan arbeitet nur auf den bereits bekannten DB-Pfaden und startet keine Videoanalyse."
    )
    owner.nfo_status_label.setWordWrap(True)
    grid.addWidget(owner.nfo_progress, 10, 0, 1, 3)
    grid.addWidget(owner.nfo_status_label, 11, 0, 1, 3)
    layout.addWidget(group)


def _create_action_buttons(owner, actions) -> dict[str, QPushButton]:
    specs = {
        "new": ("Neue DB anlegen", actions.create_empty_database),
        "import": ("Jellyfin importieren", actions.import_jellyfin),
        "scan": ("Speicherpfade scannen", actions.scan_storage_paths),
        "scan_abort": ("Scan abbrechen", actions.abort_storage_scan),
        "nfo_light": ("NFO-Lightscan", actions.scan_nfo_light),
        "nfo_full": ("NFO vollständig prüfen", actions.scan_nfo_full),
        "nfo_abort": ("NFO-Scan abbrechen", actions.abort_nfo_scan),
        "export": ("DB exportieren", actions.export_database),
        "export_csv": ("DB als CSV exportieren", actions.export_database_csv),
        "normalize": ("Streamtypen normalisieren", actions.normalize_stream_types),
        "cleanup": ("Inaktive Einträge bereinigen", actions.cleanup_inactive_items),
        "save": ("Einstellungen speichern", actions.save),
    }
    buttons: dict[str, QPushButton] = {}
    for key, (label, callback) in specs.items():
        button = QPushButton(label)
        button.clicked.connect(callback)
        buttons[key] = button

    buttons["scan_abort"].setEnabled(False)
    buttons["nfo_abort"].setEnabled(False)
    buttons["nfo_light"].setToolTip(
        "Prüft nur fehlende, unbekannte oder seit dem letzten Scan geänderte NFOs."
    )
    buttons["nfo_full"].setToolTip(
        "Liest alle bekannten NFOs neu ein und vergleicht sie mit der Mediathek-Datenbank."
    )

    owner.scan_btn = buttons["scan"]
    owner.scan_abort_btn = buttons["scan_abort"]
    owner.nfo_light_btn = buttons["nfo_light"]
    owner.nfo_full_btn = buttons["nfo_full"]
    owner.nfo_abort_btn = buttons["nfo_abort"]
    sensitive = [
        buttons[key]
        for key in (
            "new", "import", "scan", "export", "export_csv", "normalize",
            "cleanup", "save", "nfo_light", "nfo_full",
        )
    ]
    owner.scan_sensitive_widgets = list(sensitive)
    owner.nfo_scan_sensitive_widgets = list(sensitive)
    return buttons
