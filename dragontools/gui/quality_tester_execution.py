# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox, QTableWidgetItem

from ..core.path_defaults import app_documents_dir
from ..worker.quality_test_thread import QualityTestThread
from .quality_worker_lifecycle import start_owned_quality_worker, connect_quality_worker


class QualityTesterExecutionMixin:
    def _start(self) -> None:
        if self._worker is not None:
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
        factory = lambda: QualityTestThread(
            files,
            self.output_dir.text().strip() or str(app_documents_dir() / "QualityTests"),
            runs,
            sample_count=self.segment_count.value(),
            sample_duration_s=self.segment_duration.value(),
            manual_ranges=self.manual_ranges.text(),
            parent=self,
        )
        start_owned_quality_worker(self, factory=factory, wire=self._wire_worker,
            set_running=self._set_running, report_error=lambda message: self._log(f"❌ Start fehlgeschlagen: {message}"))

    def _wire_worker(self, worker) -> None:
        connect_quality_worker(self, worker, log_line=self._log, progress=self.progress.setValue,
            result_ready=self._add_result, finished=self._finished)

    def iter_shutdown_workers(self) -> tuple:
        return (self._worker,) if self._worker is not None else ()

    def _cancel(self) -> None:
        if self._worker:
            self._worker.cancel()

    def _finished(self) -> None:
        worker = self._worker
        outcome = str(getattr(worker, "outcome", "error") or "error")
        self._set_running(False)
        self._worker = None
        if outcome == "success":
            self._log("✅ Qualitätstest erfolgreich beendet.")
        elif outcome == "cancelled":
            self._log("⏹ Qualitätstest abgebrochen.")
        else:
            self._log("❌ Qualitätstest mit Fehler beendet.")

    def _set_running(self, running: bool) -> None:
        self.start_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)
        for widget in (
            self.add_files_btn, self.add_folder_btn, self.remove_btn, self.clear_btn,
            self.add_run_btn, self.remove_run_btn, self.compare_files_btn,
            self.file_table, self.run_table, self.output_dir, self.output_btn,
            self.segment_count, self.segment_duration, self.manual_ranges,
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
