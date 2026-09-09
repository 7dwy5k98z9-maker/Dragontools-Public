# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..core.paths import VIDEO_EXTENSIONS, is_video_file, path_compare_key
from ..worker.quality_compare_thread import QualityCompareThread
from .info_button import InfoButton
from .ui_helpers import install_persistent_window_geometry


class QualityFileCompareDialog(QDialog):
    """Direkter A/B-Vergleich zweier bereits vorhandener Videodateien."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._worker: QualityCompareThread | None = None
        self.setWindowTitle("Qualitätstester – Datei A/B vergleichen")
        self.setMinimumSize(900, 650)
        self._init_ui()
        install_persistent_window_geometry(self, "quality_file_compare_dialog")

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(8)

        hint = QLabel(
            "Datei A ist die Referenz. Datei B wird relativ dazu mit SSIM/VMAF bewertet. "
            "Ohne Originalquelle ist das kein absoluter Qualitätsentscheid, sondern ein belastbarer "
            "Ähnlichkeitsvergleich plus Größen-/Technikvergleich."
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        files_grid = QGridLayout()
        files_grid.addWidget(QLabel("Datei A (Referenz):"), 0, 0)
        self.file_a_edit = QLineEdit()
        self.file_a_edit.setPlaceholderText("z. B. größere / höherwertige Version")
        files_grid.addWidget(self.file_a_edit, 0, 1)
        self.file_a_btn = QPushButton("📁")
        files_grid.addWidget(self.file_a_btn, 0, 2)

        files_grid.addWidget(QLabel("Datei B (Kandidat):"), 1, 0)
        self.file_b_edit = QLineEdit()
        self.file_b_edit.setPlaceholderText("z. B. kleinere / alternative Version")
        files_grid.addWidget(self.file_b_edit, 1, 1)
        self.file_b_btn = QPushButton("📁")
        files_grid.addWidget(self.file_b_btn, 1, 2)

        self.swap_btn = QPushButton("⇄ A / B tauschen")
        files_grid.addWidget(self.swap_btn, 2, 0)
        offset_label = QLabel("Zeitversatz B:")
        offset_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        files_grid.addWidget(offset_label, 2, 1)
        self.offset_b = QDoubleSpinBox()
        self.offset_b.setRange(-300.0, 300.0)
        self.offset_b.setDecimals(3)
        self.offset_b.setSingleStep(0.1)
        self.offset_b.setSuffix(" s")
        self.offset_b.setToolTip(
            "Positiv: derselbe Inhalt beginnt in B später. Negativ: derselbe Inhalt beginnt in B früher."
        )
        files_grid.addWidget(self.offset_b, 2, 2)
        root.addLayout(files_grid)

        segment_grid = QGridLayout()
        segment_grid.addWidget(QLabel("Automatische Segmente:"), 0, 0)
        self.segment_count = QSpinBox()
        self.segment_count.setRange(1, 20)
        self.segment_count.setValue(5)
        segment_grid.addWidget(self.segment_count, 0, 1)
        segment_grid.addWidget(QLabel("Dauer je Segment:"), 0, 2)
        self.segment_duration = QSpinBox()
        self.segment_duration.setRange(2, 300)
        self.segment_duration.setValue(20)
        self.segment_duration.setSuffix(" s")
        segment_grid.addWidget(self.segment_duration, 0, 3)
        segment_grid.addWidget(
            InfoButton(
                "Die Segmente werden gleichmäßig über die gemeinsame Laufzeit verteilt.\n"
                "Manuelle Beispiele: 10%+20, 00:12:30+30, 01:05:00+20.\n"
                "Bei anderem Intro/Schnitt zuerst den Zeitversatz anpassen."
            ),
            0,
            4,
        )
        segment_grid.addWidget(QLabel("Manuelle Bereiche:"), 1, 0)
        self.manual_ranges = QLineEdit()
        self.manual_ranges.setPlaceholderText("optional: 10%+20, 00:12:30+30")
        segment_grid.addWidget(self.manual_ranges, 1, 1, 1, 4)
        root.addLayout(segment_grid)

        action_row = QHBoxLayout()
        self.start_btn = QPushButton("🔎 Dateien vergleichen")
        self.cancel_btn = QPushButton("⛔ Abbrechen")
        self.cancel_btn.setEnabled(False)
        self.progress = QProgressBar()
        action_row.addWidget(self.start_btn)
        action_row.addWidget(self.cancel_btn)
        action_row.addWidget(self.progress, 1)
        root.addLayout(action_row)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.summary.setVisible(False)
        root.addWidget(self.summary)

        self.result_table = QTableWidget()
        self.result_table.setColumnCount(6)
        self.result_table.setHorizontalHeaderLabels(["Segment", "Start A", "Start B", "SSIM", "VMAF", "Hinweis"])
        self.result_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.result_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.result_table.setMinimumHeight(170)
        root.addWidget(self.result_table, 1)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.log.setMinimumHeight(150)
        root.addWidget(self.log, 1)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        self.close_btn = QPushButton("Schließen")
        close_row.addWidget(self.close_btn)
        root.addLayout(close_row)

        self.file_a_btn.clicked.connect(lambda: self._choose_file(self.file_a_edit, "Referenzdatei A auswählen"))
        self.file_b_btn.clicked.connect(lambda: self._choose_file(self.file_b_edit, "Kandidatdatei B auswählen"))
        self.swap_btn.clicked.connect(self._swap_files)
        self.start_btn.clicked.connect(self._start)
        self.cancel_btn.clicked.connect(self._cancel)
        self.close_btn.clicked.connect(self.close)

    def _choose_file(self, target: QLineEdit, caption: str) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            caption,
            target.text().strip(),
            f"Video-Dateien ({' '.join('*' + ext for ext in sorted(VIDEO_EXTENSIONS))})",
        )
        if file_path:
            target.setText(str(Path(file_path).resolve()))

    def _swap_files(self) -> None:
        file_a = self.file_a_edit.text()
        self.file_a_edit.setText(self.file_b_edit.text())
        self.file_b_edit.setText(file_a)
        self.offset_b.setValue(-self.offset_b.value())

    def _start(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        file_a = self.file_a_edit.text().strip()
        file_b = self.file_b_edit.text().strip()
        if not self._valid_video(file_a):
            QMessageBox.warning(self, "Dateivergleich", "Bitte eine gültige Videodatei A auswählen.")
            return
        if not self._valid_video(file_b):
            QMessageBox.warning(self, "Dateivergleich", "Bitte eine gültige Videodatei B auswählen.")
            return
        if path_compare_key(file_a) == path_compare_key(file_b):
            QMessageBox.information(self, "Dateivergleich", "Bitte zwei unterschiedliche Dateien auswählen.")
            return

        self.result_table.setRowCount(0)
        self.summary.clear()
        self.summary.setVisible(False)
        self.log.clear()
        self.progress.setValue(0)
        self._set_running(True)

        worker = QualityCompareThread(
            file_a,
            file_b,
            sample_count=self.segment_count.value(),
            sample_duration_s=self.segment_duration.value(),
            manual_ranges=self.manual_ranges.text(),
            offset_b_s=self.offset_b.value(),
            parent=self,
        )
        self._worker = worker
        worker.log_line.connect(self.log.appendPlainText)
        worker.progress.connect(self.progress.setValue)
        worker.result_ready.connect(self._add_result)
        worker.summary_ready.connect(self._show_summary)
        worker.finished.connect(self._finished)
        worker.start()

    @staticmethod
    def _valid_video(path: str) -> bool:
        candidate = Path(path)
        return candidate.is_file() and is_video_file(candidate)

    def _cancel(self) -> None:
        if self._worker:
            self._worker.cancel()

    def _finished(self) -> None:
        self._set_running(False)
        self._worker = None
        self.log.appendPlainText("✅ Dateivergleich beendet.")

    def _set_running(self, running: bool) -> None:
        self.start_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)
        self.close_btn.setEnabled(not running)
        for widget in (
            self.file_a_edit,
            self.file_b_edit,
            self.file_a_btn,
            self.file_b_btn,
            self.swap_btn,
            self.offset_b,
            self.segment_count,
            self.segment_duration,
            self.manual_ranges,
        ):
            widget.setEnabled(not running)

    def _add_result(self, result) -> None:
        row = self.result_table.rowCount()
        self.result_table.insertRow(row)
        notes = "; ".join(str(note) for note in (getattr(result, "notes", []) or []))
        values = [
            getattr(result, "segment_label", ""),
            f"{float(getattr(result, 'start_a_s', 0.0) or 0.0):.3f}s",
            f"{float(getattr(result, 'start_b_s', 0.0) or 0.0):.3f}s",
            f"{result.ssim:.5f}" if getattr(result, "ssim", None) is not None else "n/v",
            f"{result.vmaf:.2f}" if getattr(result, "vmaf", None) is not None else "n/v",
            notes,
        ]
        for col, value in enumerate(values):
            self.result_table.setItem(row, col, QTableWidgetItem(str(value)))

    @staticmethod
    def _format_file_info(info) -> str:
        size_gib = float(getattr(info, "size_bytes", 0) or 0) / 1024 / 1024 / 1024
        duration = float(getattr(info, "duration_s", 0.0) or 0.0)
        return (
            f"{getattr(info, 'name', '')} | {getattr(info, 'width', 0)}×{getattr(info, 'height', 0)} | "
            f"{getattr(info, 'codec', '')} {getattr(info, 'pix_fmt', '')} | {getattr(info, 'hdr_label', '')} | "
            f"{duration:.1f}s | {size_gib:.2f} GiB"
        )

    def _show_summary(self, summary) -> None:
        avg_ssim = getattr(summary, "average_ssim", None)
        avg_vmaf = getattr(summary, "average_vmaf", None)
        ssim_text = f"{avg_ssim:.5f}" if avg_ssim is not None else "n/v"
        vmaf_text = f"{avg_vmaf:.2f}" if avg_vmaf is not None else "n/v"
        self.summary.setText(
            f"<b>A – Referenz:</b> {self._format_file_info(summary.file_a)}<br>"
            f"<b>B – Kandidat:</b> {self._format_file_info(summary.file_b)}<br>"
            f"<b>Ø SSIM {ssim_text} | Ø VMAF {vmaf_text}</b> über "
            f"{int(getattr(summary, 'compared_segments', 0) or 0)} Segmente<br>"
            f"{getattr(summary, 'assessment', '')}"
        )
        self.summary.setVisible(True)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._worker and self._worker.isRunning():
            QMessageBox.information(self, "Dateivergleich", "Bitte den laufenden Vergleich zuerst abbrechen.")
            event.ignore()
            return
        super().closeEvent(event)
