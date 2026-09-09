# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox, QTableWidgetItem

from ..core.paths import app_documents_dir
from ..worker.quality_test_thread import QualityTestThread


class QualityTesterExecutionMixin:
    def _start(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        files = self._collect_files()
        if not files:
            QMessageBox.information(self, "Qualitätstest", "Bitte zuerst Videodateien hinzufügen.")
            return
        runs = self._collect_runs()
        if len(runs) < 2:
            QMessageBox.information(self, "Qualitätstest", "Bitte mindestens zwei aktive Testläufe definieren.")
            return
        self.result_table.setRowCount(0)
        self.progress.setValue(0)
        self.log.clear()
        self._set_running(True)
        self._worker = QualityTestThread(
            files,
            self.output_dir.text().strip() or str(app_documents_dir() / "QualityTests"),
            runs,
            sample_count=self.segment_count.value(),
            sample_duration_s=self.segment_duration.value(),
            manual_ranges=self.manual_ranges.text(),
            parent=self,
        )
        self._worker.log_line.connect(self._log)
        self._worker.progress.connect(self.progress.setValue)
        self._worker.result_ready.connect(self._add_result)
        self._worker.finished.connect(self._finished)
        self._worker.start()

    def iter_shutdown_workers(self) -> tuple:
        return (self._worker,) if self._worker is not None else ()

    def _cancel(self) -> None:
        if self._worker:
            self._worker.cancel()

    def _finished(self) -> None:
        self._set_running(False)
        self._worker = None
        self._log("✅ Qualitätstest beendet.")

    def _set_running(self, running: bool) -> None:
        self.start_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)
        for widget in (
            self.add_files_btn, self.add_folder_btn, self.remove_btn, self.clear_btn,
            self.add_run_btn, self.remove_run_btn, self.compare_files_btn,
        ):
            widget.setEnabled(not running)

    def _log(self, line: str) -> None:
        self.log.appendPlainText(str(line))

    def _add_result(self, result) -> None:
        row = self.result_table.rowCount()
        self.result_table.insertRow(row)
        size_mb = float(getattr(result, "size_bytes", 0) or 0) / 1024 / 1024
        values = [
            getattr(result, "run_name", ""),
            getattr(result, "segment_label", ""),
            f"{size_mb:.2f} MB",
            f"{float(getattr(result, 'video_bitrate_kbps', 0.0) or 0.0):.0f} kbps",
            f"{getattr(result, 'codec', '')} {getattr(result, 'profile', '')}".strip(),
            getattr(result, "pix_fmt", ""),
            f"{result.ssim:.5f}" if getattr(result, "ssim", None) is not None else "n/v",
            f"{result.vmaf:.2f}" if getattr(result, "vmaf", None) is not None else "n/v",
        ]
        for col, value in enumerate(values):
            self.result_table.setItem(row, col, QTableWidgetItem(str(value)))
