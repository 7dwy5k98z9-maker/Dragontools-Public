# -*- coding: utf-8 -*-
"""Fix-Queue tab construction for the media-library dialog."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QSpinBox,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)


def build_fix_tab(owner, actions) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)

    intro = QLabel(
        "Findet reparierbare Mediathek-Probleme und führt die ausgewählten Aktionen seriell aus. "
        "NFO/Trickplay werden nur ergänzt. Sprache/Tracktitel werden konservativ korrigiert. "
        "Patch J erzeugt für PGS/VobSub zunächst nur einen OCR-Entwurf; ein SRT entsteht erst nach manueller Prüfung."
    )
    intro.setWordWrap(True)
    layout.addWidget(intro)

    _build_discovery_group(owner, actions, layout)
    _build_queue_group(owner, actions, layout)
    return page


def _build_discovery_group(owner, actions, layout: QVBoxLayout) -> None:
    group = QGroupBox("Gefundene Probleme")
    box = QVBoxLayout(group)
    controls = QHBoxLayout()
    owner.fix_scan_btn = QPushButton("Probleme prüfen")
    owner.fix_scan_btn.clicked.connect(actions.scan_fix_issues)
    owner.fix_add_selected_btn = QPushButton("Ausgewählte → Fix Queue")
    owner.fix_add_selected_btn.clicked.connect(actions.queue_selected_fix_issues)
    owner.fix_add_all_btn = QPushButton("Alle → Fix Queue")
    owner.fix_add_all_btn.clicked.connect(actions.queue_all_fix_issues)
    controls.addWidget(owner.fix_scan_btn)
    controls.addWidget(owner.fix_add_selected_btn)
    controls.addWidget(owner.fix_add_all_btn)
    controls.addStretch(1)
    box.addLayout(controls)

    categories = QHBoxLayout()
    categories.addWidget(QLabel("Prüfen:"))
    owner.fix_nfo_cb = QCheckBox("fehlende NFOs")
    owner.fix_trickplay_cb = QCheckBox("fehlendes/leeres Trickplay")
    owner.fix_metadata_cb = QCheckBox("unvollständige Medienanalyse")
    owner.fix_streams_cb = QCheckBox("Sprache / Tracktitel")
    owner.fix_ocr_cb = QCheckBox("PGS/VobSub OCR")
    owner.fix_nfo_cb.setChecked(True)
    owner.fix_trickplay_cb.setChecked(True)
    owner.fix_metadata_cb.setChecked(True)
    owner.fix_streams_cb.setChecked(True)
    owner.fix_ocr_cb.setChecked(False)
    categories.addWidget(owner.fix_nfo_cb)
    categories.addWidget(owner.fix_trickplay_cb)
    categories.addWidget(owner.fix_metadata_cb)
    categories.addWidget(owner.fix_streams_cb)
    categories.addWidget(owner.fix_ocr_cb)
    categories.addStretch(1)
    box.addLayout(categories)

    language_options = QHBoxLayout()
    language_options.addWidget(QLabel("Spracherkennung:"))
    owner.fix_language_model_combo = QComboBox()
    owner.fix_language_model_combo.addItems(["tiny", "base", "small", "medium", "large-v3"])
    owner.fix_language_model_combo.setCurrentText("small")
    owner.fix_language_confidence_spin = QSpinBox()
    owner.fix_language_confidence_spin.setRange(50, 99)
    owner.fix_language_confidence_spin.setSuffix(" %")
    owner.fix_language_confidence_spin.setValue(85)
    owner.fix_language_samples_spin = QSpinBox()
    owner.fix_language_samples_spin.setRange(1, 7)
    owner.fix_language_samples_spin.setValue(3)
    owner.fix_language_seconds_spin = QSpinBox()
    owner.fix_language_seconds_spin.setRange(5, 60)
    owner.fix_language_seconds_spin.setSuffix(" s")
    owner.fix_language_seconds_spin.setValue(15)
    language_options.addWidget(QLabel("Whisper-Modell"))
    language_options.addWidget(owner.fix_language_model_combo)
    language_options.addWidget(QLabel("Min. Konfidenz"))
    language_options.addWidget(owner.fix_language_confidence_spin)
    language_options.addWidget(QLabel("Audio-Samples"))
    language_options.addWidget(owner.fix_language_samples_spin)
    language_options.addWidget(QLabel("je"))
    language_options.addWidget(owner.fix_language_seconds_spin)
    language_options.addStretch(1)
    box.addLayout(language_options)

    ocr_options = QHBoxLayout()
    ocr_options.addWidget(QLabel("Bitmap-OCR:"))
    owner.fix_ocr_languages_edit = QLineEdit("deu+eng")
    owner.fix_ocr_languages_edit.setPlaceholderText("Tesseract-Sprachen, z. B. deu+eng+jpn")
    owner.fix_ocr_languages_edit.setMaximumWidth(220)
    owner.fix_ocr_confidence_spin = QSpinBox()
    owner.fix_ocr_confidence_spin.setRange(30, 99)
    owner.fix_ocr_confidence_spin.setSuffix(" %")
    owner.fix_ocr_confidence_spin.setValue(75)
    ocr_options.addWidget(QLabel("Sprachdaten"))
    ocr_options.addWidget(owner.fix_ocr_languages_edit)
    ocr_options.addWidget(QLabel("Unsicher unter"))
    ocr_options.addWidget(owner.fix_ocr_confidence_spin)
    ocr_options.addWidget(QLabel("→ Review erforderlich; Originalspur bleibt erhalten"))
    ocr_options.addStretch(1)
    box.addLayout(ocr_options)

    owner.fix_issue_label = QLabel("Noch keine Prüfung durchgeführt.")
    box.addWidget(owner.fix_issue_label)
    owner.fix_issue_table = _new_fix_table(include_result=False)
    box.addWidget(owner.fix_issue_table, 1)
    layout.addWidget(group, 1)


def _build_queue_group(owner, actions, layout: QVBoxLayout) -> None:
    group = QGroupBox("Fix Queue")
    box = QVBoxLayout(group)
    controls = QHBoxLayout()
    owner.fix_remove_btn = QPushButton("Ausgewählte entfernen")
    owner.fix_remove_btn.clicked.connect(actions.remove_selected_fix_items)
    owner.fix_clear_btn = QPushButton("Queue leeren")
    owner.fix_clear_btn.clicked.connect(actions.clear_fix_queue)
    owner.fix_run_btn = QPushButton("▶ Fix Queue ausführen")
    owner.fix_run_btn.clicked.connect(actions.run_fix_queue)
    owner.fix_review_ocr_btn = QPushButton("OCR-Entwurf prüfen")
    owner.fix_review_ocr_btn.clicked.connect(actions.review_selected_ocr_draft)
    owner.fix_abort_btn = QPushButton("Abbrechen")
    owner.fix_abort_btn.clicked.connect(actions.abort_fix_queue)
    owner.fix_abort_btn.setEnabled(False)
    controls.addWidget(owner.fix_remove_btn)
    controls.addWidget(owner.fix_clear_btn)
    controls.addStretch(1)
    controls.addWidget(owner.fix_review_ocr_btn)
    controls.addWidget(owner.fix_run_btn)
    controls.addWidget(owner.fix_abort_btn)
    box.addLayout(controls)

    owner.fix_queue_table = _new_fix_table(include_result=True)
    box.addWidget(owner.fix_queue_table, 1)
    owner.fix_progress = QProgressBar()
    owner.fix_progress.setRange(0, 100)
    owner.fix_progress.setValue(0)
    owner.fix_status_label = QLabel("Fix Queue ist leer.")
    owner.fix_status_label.setWordWrap(True)
    box.addWidget(owner.fix_progress)
    box.addWidget(owner.fix_status_label)
    layout.addWidget(group, 1)

    owner.fix_sensitive_widgets = [
        owner.fix_scan_btn,
        owner.fix_add_selected_btn,
        owner.fix_add_all_btn,
        owner.fix_remove_btn,
        owner.fix_clear_btn,
        owner.fix_run_btn,
        owner.fix_nfo_cb,
        owner.fix_trickplay_cb,
        owner.fix_metadata_cb,
        owner.fix_streams_cb,
        owner.fix_ocr_cb,
        owner.fix_language_model_combo,
        owner.fix_language_confidence_spin,
        owner.fix_language_samples_spin,
        owner.fix_language_seconds_spin,
        owner.fix_ocr_languages_edit,
        owner.fix_ocr_confidence_spin,
        owner.fix_review_ocr_btn,
    ]


def _new_fix_table(*, include_result: bool) -> QTableWidget:
    headers = ["Problem", "Aktion", "Titel", "Typ", "Pfad"]
    if include_result:
        headers += ["Status", "Ergebnis"]
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    header = table.horizontalHeader()
    for index in range(len(headers)):
        header.setSectionResizeMode(index, QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
    table.setSortingEnabled(False)
    return table


__all__ = ["build_fix_tab"]
