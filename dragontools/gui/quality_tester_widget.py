# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6.QtWidgets import (
    QGridLayout, QGroupBox, QHeaderView, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QProgressBar, QPushButton, QSpinBox, QTableWidget,
    QVBoxLayout, QWidget,
)

from ..core.paths import app_documents_dir
from ..core.settings import APP_VERSION
from ..worker.quality_test_thread import QualityTestThread
from .file_drop_widgets import FileDropTable
from .info_button import InfoButton
from .quality_file_compare_dialog import QualityFileCompareDialog
from .quality_tester_execution import QualityTesterExecutionMixin
from .quality_tester_files import QualityTesterFilesMixin
from .quality_tester_run_config import QualityTesterRunConfigMixin


class _QualityFileTable(FileDropTable):
    pass


class QualityTesterWidget(
    QualityTesterRunConfigMixin,
    QualityTesterFilesMixin,
    QualityTesterExecutionMixin,
    QWidget,
):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._worker: QualityTestThread | None = None
        self._init_ui()

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        title = QLabel(f"🧪 Qualitätstester – Dragon Tools V{APP_VERSION}")
        title.setStyleSheet("font-weight:bold;font-size:15px;")
        root.addWidget(title)

        hint = QLabel(
            "Kurze Testsegmente encodieren, Ausgabe technisch prüfen und SSIM/VMAF messen, "
            "wenn dein FFmpeg die Filter unterstützt."
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        toolbar = QHBoxLayout()
        self.add_files_btn = QPushButton("➕ Dateien")
        self.add_folder_btn = QPushButton("📁 Ordner")
        self.remove_btn = QPushButton("➖ Entfernen")
        self.clear_btn = QPushButton("🗑 Alle")
        self.compare_files_btn = QPushButton("🔎 Datei A/B vergleichen")
        for btn in (self.add_files_btn, self.add_folder_btn, self.remove_btn, self.clear_btn):
            toolbar.addWidget(btn)
        toolbar.addStretch(1)
        toolbar.addWidget(self.compare_files_btn)
        root.addLayout(toolbar)

        self.file_table = _QualityFileTable()
        self.file_table.setColumnCount(2)
        self.file_table.setHorizontalHeaderLabels(["Datei", "Pfad"])
        self.file_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.file_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.file_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.file_table.setMinimumHeight(120)
        root.addWidget(self.file_table, 1)

        settings_box = QGroupBox("Testbereiche")
        sg = QGridLayout(settings_box)
        sg.addWidget(QLabel("Automatische Segmente:"), 0, 0)
        self.segment_count = QSpinBox()
        self.segment_count.setRange(1, 20)
        self.segment_count.setValue(3)
        sg.addWidget(self.segment_count, 0, 1)
        sg.addWidget(QLabel("Dauer je Segment:"), 0, 2)
        self.segment_duration = QSpinBox()
        self.segment_duration.setRange(2, 300)
        self.segment_duration.setValue(20)
        self.segment_duration.setSuffix(" s")
        sg.addWidget(self.segment_duration, 0, 3)
        sg.addWidget(InfoButton(
            "Ohne manuelle Bereiche verteilt DragonTools die Segmente gleichmäßig über die Laufzeit.\n"
            "Für schwierige Szenen kannst du manuell Bereiche eintragen, z.B.:\n"
            "10%+20, 00:12:30+30, 01:05:00+20"
        ), 0, 4)
        sg.addWidget(QLabel("Manuelle Bereiche:"), 1, 0)
        self.manual_ranges = QLineEdit()
        self.manual_ranges.setPlaceholderText("optional: 10%+20, 00:12:30+30")
        sg.addWidget(self.manual_ranges, 1, 1, 1, 4)
        sg.addWidget(QLabel("Ausgabeordner:"), 2, 0)
        self.output_dir = QLineEdit(str(app_documents_dir() / "QualityTests"))
        sg.addWidget(self.output_dir, 2, 1, 1, 3)
        self.output_btn = QPushButton("📁")
        sg.addWidget(self.output_btn, 2, 4)
        root.addWidget(settings_box)

        runs_box = QGroupBox("Testläufe")
        rv = QVBoxLayout(runs_box)
        run_toolbar = QHBoxLayout()
        self.add_run_btn = QPushButton("➕ Testlauf")
        self.remove_run_btn = QPushButton("➖ Testlauf")
        run_toolbar.addWidget(self.add_run_btn)
        run_toolbar.addWidget(self.remove_run_btn)
        run_toolbar.addStretch(1)
        rv.addLayout(run_toolbar)

        self.run_table = QTableWidget()
        self.run_table.setColumnCount(9)
        self.run_table.setHorizontalHeaderLabels(
            ["Aktiv", "Name", "Codec", "Encoder", "Qualität", "Preset", "Bit", "Skalierung", "Extra-Args"]
        )
        self.run_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.run_table.horizontalHeader().setSectionResizeMode(self.RUN_COL_EXTRA, QHeaderView.ResizeMode.Stretch)
        self.run_table.setMinimumHeight(110)
        rv.addWidget(self.run_table)
        root.addWidget(runs_box)
        self._add_default_runs()

        action_row = QHBoxLayout()
        self.start_btn = QPushButton("🧪 Qualitätstest starten")
        self.cancel_btn = QPushButton("⛔ Abbrechen")
        self.cancel_btn.setEnabled(False)
        self.progress = QProgressBar()
        action_row.addWidget(self.start_btn)
        action_row.addWidget(self.cancel_btn)
        action_row.addWidget(self.progress, 1)
        root.addLayout(action_row)

        self.result_table = QTableWidget()
        self.result_table.setColumnCount(8)
        self.result_table.setHorizontalHeaderLabels(
            ["Testlauf", "Segment", "Größe", "Bitrate", "Codec", "PixFmt", "SSIM", "VMAF"]
        )
        self.result_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.result_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.result_table.setMinimumHeight(120)
        root.addWidget(self.result_table, 1)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.log.setMinimumHeight(120)
        root.addWidget(self.log, 1)

        self.add_files_btn.clicked.connect(self._add_files_dialog)
        self.add_folder_btn.clicked.connect(self._add_folder_dialog)
        self.remove_btn.clicked.connect(self._remove_selected_files)
        self.clear_btn.clicked.connect(lambda: self.file_table.setRowCount(0))
        self.compare_files_btn.clicked.connect(self._open_file_compare_dialog)
        self.file_table.paths_dropped.connect(self._add_paths)
        self.output_btn.clicked.connect(self._choose_output_dir)
        self.add_run_btn.clicked.connect(self._add_run_dialog)
        self.remove_run_btn.clicked.connect(self._remove_selected_runs)
        self.run_table.cellDoubleClicked.connect(lambda row, _col: self._edit_run_row(row))
        self.start_btn.clicked.connect(self._start)
        self.cancel_btn.clicked.connect(self._cancel)

    def _open_file_compare_dialog(self) -> None:
        dialog = QualityFileCompareDialog(parent=self)
        dialog.exec()

    def iter_shutdown_workers(self):
        """Explicit tab lifecycle contract; implementation lives in the execution mixin."""
        return QualityTesterExecutionMixin.iter_shutdown_workers(self)
