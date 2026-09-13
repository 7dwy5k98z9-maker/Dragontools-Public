# -*- coding: utf-8 -*-
from __future__ import annotations

import subprocess
import threading
import traceback
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from ..core.tool_paths import get_tool_paths
from .process_control import terminate_process_tree
from .quality_compare_service import QualityCompareService
from .quality_metrics_service import QualityMetricsService
from .quality_process_runner import QualityProcessRunner


class QualityCompareThread(QThread):
    """Qt lifecycle adapter for segment-wise comparison of two existing videos."""

    log_line = pyqtSignal(str)
    progress = pyqtSignal(int)
    result_ready = pyqtSignal(object)
    summary_ready = pyqtSignal(object)
    finished = pyqtSignal()

    def __init__(self, file_a: str, file_b: str, *, sample_count: int = 3, sample_duration_s: int = 20,
                 manual_ranges: str = "", offset_b_s: float = 0.0, parent=None) -> None:
        super().__init__(parent)
        self.file_a = str(Path(file_a).resolve())
        self.file_b = str(Path(file_b).resolve())
        self.sample_count = max(1, min(20, int(sample_count or 3)))
        self.sample_duration_s = max(1, int(sample_duration_s or 20))
        self.manual_ranges = str(manual_ranges or "")
        self.offset_b_s = float(offset_b_s or 0.0)
        self.tools = get_tool_paths()
        self.current_process: subprocess.Popen | None = None
        self._process_lock = threading.Lock()
        self._abort = False
        self.abort_requested = False
        self.abort_type: str | None = None
        self._process_runner = QualityProcessRunner(worker=self, log=self.log_line.emit, prefix="Qualitätsvergleich")
        self._metrics = QualityMetricsService(ffmpeg=self.tools.ffmpeg, process_runner=self._process_runner)
        self._service = QualityCompareService(
            tools=self.tools,
            metrics=self._metrics,
            log=self.log_line.emit,
            progress=self.progress.emit,
            result_ready=self.result_ready.emit,
            summary_ready=self.summary_ready.emit,
            is_aborted=lambda: self._abort,
        )

    def cancel(self) -> None:
        self._abort = True
        self.abort_requested = True
        self.abort_type = "sofort"
        terminate_process_tree(
            self, self._process_lock,
            log=lambda message, _level="warn": self.log_line.emit(message),
            attr_name="current_process", label="Qualitätsvergleich-Prozess",
        )

    def run(self) -> None:
        try:
            self._run()
        except Exception:
            self.log_line.emit("❌ Unbehandelte Ausnahme im Dateivergleich:")
            self.log_line.emit(traceback.format_exc())
        finally:
            with self._process_lock:
                self.current_process = None
            self.finished.emit()

    def _run(self) -> None:
        self._service.run(
            file_a=self.file_a, file_b=self.file_b,
            sample_count=self.sample_count, sample_duration_s=self.sample_duration_s,
            manual_ranges=self.manual_ranges, offset_b_s=self.offset_b_s,
        )

    @staticmethod
    def _average(values):
        return QualityCompareService.average(values)

    @staticmethod
    def _file_info(media, path: str):
        return QualityCompareService.file_info(media, path)

    def _run_process(self, cmd: list[str], *, label: str):
        return self._process_runner.run(cmd, label=label)

    @staticmethod
    def _metric_filter(metric: str, width: int, height: int) -> str:
        return QualityMetricsService.comparison_filter(metric, width, height)

    def _metric_command(self, metric: str, start_a: float, start_b: float, duration: float, width: int, height: int) -> list[str]:
        return [
            str(self.tools.ffmpeg), "-hide_banner", "-nostats", "-v", "info",
            "-ss", f"{start_a:.6f}", "-i", self.file_a,
            "-ss", f"{start_b:.6f}", "-i", self.file_b,
            "-t", f"{duration:.6f}", "-filter_complex", self._metric_filter(metric, width, height),
            "-f", "null", "-",
        ]

    def _measure_ssim(self, start_a, start_b, duration, width, height, notes):
        return self._metrics.measure_comparison(metric="ssim", file_a=self.file_a, file_b=self.file_b,
            start_a=start_a, start_b=start_b, duration=duration, width=width, height=height, label="SSIM A↔B", notes=notes)

    def _measure_vmaf(self, start_a, start_b, duration, width, height, notes):
        return self._metrics.measure_comparison(metric="libvmaf", file_a=self.file_a, file_b=self.file_b,
            start_a=start_a, start_b=start_b, duration=duration, width=width, height=height, label="VMAF B gegen A", notes=notes)

    def _log_result(self, result) -> None:
        self._service.log_result(result)
