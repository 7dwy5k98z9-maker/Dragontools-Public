# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from ..core.paths import app_documents_dir
from ..core.settings import APP_VERSION
from .info_button import InfoButton


class AudioVideoMatcherViewMixin:
    """Builds the matcher UI and owns presentation-only state changes."""

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        title = QLabel(f"🎧 Audio-Video-Matcher – Dragon Tools V{APP_VERSION}")
        title.setStyleSheet("font-weight:bold;font-size:15px;")
        root.addWidget(title)

        hint = QLabel(
            "Vergleicht zwei Videoversionen, erkennt Offset, gleichmäßige Drift oder Schnittunterschiede "
            "und erstellt daraus eine MKV mit Zielvideo und synchronisierter deutscher Audiospur."
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        file_box = QGroupBox("Dateien")
        grid = QGridLayout(file_box)
        self.source_edit = QLineEdit()
        self.target_edit = QLineEdit()
        self.output_edit = QLineEdit(str(app_documents_dir() / "AudioVideoMatcher" / "synchronisiert.mkv"))
        self.source_btn = QPushButton("📁")
        self.target_btn = QPushButton("📁")
        self.output_btn = QPushButton("📁")
        grid.addWidget(QLabel("Deutsche Quelle:"), 0, 0)
        grid.addWidget(self.source_edit, 0, 1)
        grid.addWidget(self.source_btn, 0, 2)
        grid.addWidget(QLabel("Zielvideo:"), 1, 0)
        grid.addWidget(self.target_edit, 1, 1)
        grid.addWidget(self.target_btn, 1, 2)
        grid.addWidget(QLabel("Ausgabe:"), 2, 0)
        grid.addWidget(self.output_edit, 2, 1)
        grid.addWidget(self.output_btn, 2, 2)
        root.addWidget(file_box)

        result_box = QGroupBox("Analyseergebnis")
        rg = QGridLayout(result_box)
        self.case_value = QLabel("Noch nicht analysiert")
        self.confidence_value = QLabel("-")
        self.offset_value = QLabel("-")
        self.speed_value = QLabel("-")
        self.drift_value = QLabel("-")
        self.common_value = QLabel("-")
        self.audio_combo = QComboBox()
        rg.addWidget(QLabel("Erkannter Fall:"), 0, 0)
        rg.addWidget(self.case_value, 0, 1)
        rg.addWidget(QLabel("Vertrauen:"), 0, 2)
        rg.addWidget(self.confidence_value, 0, 3)
        rg.addWidget(QLabel("Startoffset:"), 1, 0)
        rg.addWidget(self.offset_value, 1, 1)
        rg.addWidget(QLabel("Geschwindigkeitsfaktor:"), 1, 2)
        rg.addWidget(self.speed_value, 1, 3)
        rg.addWidget(QLabel("Drift:"), 2, 0)
        rg.addWidget(self.drift_value, 2, 1)
        rg.addWidget(QLabel("Gemeinsamer Bereich:"), 2, 2)
        rg.addWidget(self.common_value, 2, 3)
        rg.addWidget(QLabel("Deutsche Audiospur:"), 3, 0)
        rg.addWidget(self.audio_combo, 3, 1, 1, 3)
        root.addWidget(result_box)

        cut_box = QGroupBox("Fall C – Schnittbereiche")
        cg = QGridLayout(cut_box)
        self.cut_ranges = QLineEdit()
        self.cut_ranges.setPlaceholderText("z.B. 1,5-2,5; 15-25; 01:15-01:25;")
        cg.addWidget(QLabel("Ungefähre Bereiche:"), 0, 0)
        cg.addWidget(self.cut_ranges, 0, 1)
        cg.addWidget(
            InfoButton(
                "Gib Zielvideo-Zeitbereiche ein, in denen sich die Versionen unterscheiden.\n"
                "Eine Genauigkeit von ca. +/- 1 Sekunde reicht.\n\n"
                "Beispiele:\n"
                "1,5-2,5;15-25;\n"
                "01:15-01:25;\n"
                "01:15,500-01:25,800;"
            ),
            0,
            2,
        )
        self.refine_btn = QPushButton("🔎 Schnittbereiche analysieren")
        self.refine_btn.setEnabled(False)
        root.addWidget(cut_box)

        actions = QHBoxLayout()
        self.analyze_btn = QPushButton("🔎 Analysieren")
        self.create_btn = QPushButton("🎧 Audio anpassen und Datei erstellen")
        self.cancel_btn = QPushButton("⛔ Abbrechen")
        self.create_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.progress = QProgressBar()
        actions.addWidget(self.analyze_btn)
        actions.addWidget(self.refine_btn)
        actions.addWidget(self.create_btn)
        actions.addWidget(self.cancel_btn)
        actions.addWidget(self.progress, 1)
        root.addLayout(actions)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(3000)
        self.log.setMinimumHeight(180)
        root.addWidget(self.log, 1)

        self.source_btn.clicked.connect(
            lambda: self._choose_video(self.source_edit, "Deutsche Quellvideodatei wählen")
        )
        self.target_btn.clicked.connect(
            lambda: self._choose_video(self.target_edit, "Zielvideodatei wählen")
        )
        self.output_btn.clicked.connect(self._choose_output)
        self.target_edit.textChanged.connect(self._maybe_update_output_name)
        self.analyze_btn.clicked.connect(self._start_analyze)
        self.refine_btn.clicked.connect(self._start_refine)
        self.create_btn.clicked.connect(self._start_create)
        self.cancel_btn.clicked.connect(self._cancel)

    def _set_running(self, running: bool) -> None:
        self.analyze_btn.setEnabled(not running)
        self.refine_btn.setEnabled(
            (not running) and self._analysis is not None and self._analysis.mode == "C"
        )
        self.create_btn.setEnabled((not running) and self._can_create())
        self.cancel_btn.setEnabled(running)
        for widget in (
            self.source_btn,
            self.target_btn,
            self.output_btn,
            self.source_edit,
            self.target_edit,
            self.output_edit,
            self.cut_ranges,
        ):
            widget.setEnabled(not running)

    def _log(self, line: str) -> None:
        self.log.appendPlainText(str(line))
