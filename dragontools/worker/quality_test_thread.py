# -*- coding: utf-8 -*-
from __future__ import annotations

import subprocess
import threading
import traceback
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from ..core.quality_tester import quality_run_from_dict
from ..core.tool_paths import get_tool_paths
from .process_control import terminate_process_tree
from .quality_metrics_service import QualityMetricsService
from .quality_process_runner import QualityProcessRunner
from .quality_test_service import QualityTestService


class QualityTestThread(QThread):
    log_line = pyqtSignal(str)
    progress = pyqtSignal(int)
    result_ready = pyqtSignal(object)
    finished = pyqtSignal()

    def __init__(self, files: list[str], output_dir: str, runs: list[dict], *, sample_count: int = 3,
                 sample_duration_s: int = 20, manual_ranges: str = "", parent=None) -> None:
        super().__init__(parent)
        self.files = [str(Path(f).resolve()) for f in files]
        self.output_dir = str(Path(output_dir).resolve())
        self.runs = [quality_run_from_dict(r) for r in runs if r]
        self.sample_count = max(1, min(20, int(sample_count or 3)))
        self.sample_duration_s = max(1, int(sample_duration_s or 20))
        self.manual_ranges = str(manual_ranges or "")
        self.tools = get_tool_paths()
        self.current_process: subprocess.Popen | None = None
        self._process_lock = threading.Lock()
        self._abort = False
        self.abort_requested = False
        self.abort_type: str | None = None
        self._process_runner = QualityProcessRunner(worker=self, log=self.log_line.emit, prefix="Qualitätstest")
        self._metrics = QualityMetricsService(ffmpeg=self.tools.ffmpeg, process_runner=self._process_runner)
        self._service = QualityTestService(
            tools=self.tools, process_runner=self._process_runner, metrics=self._metrics,
            log=self.log_line.emit, progress=self.progress.emit, result_ready=self.result_ready.emit,
            is_aborted=lambda: self._abort,
        )

    def cancel(self) -> None:
        self._abort = True
        self.abort_requested = True
        self.abort_type = "sofort"
        terminate_process_tree(self, self._process_lock, log=lambda message, _level="warn": self.log_line.emit(message),
                               attr_name="current_process", label="Qualitätstester-Prozess")

    def run(self) -> None:
        try:
            self._run()
        except Exception:
            self.log_line.emit("❌ Unbehandelte Ausnahme im Qualitätstester:")
            self.log_line.emit(traceback.format_exc())
        finally:
            with self._process_lock:
                self.current_process = None
            self.finished.emit()

    def _run(self) -> None:
        self._service.run(files=self.files, output_dir=self.output_dir, runs=self.runs, sample_count=self.sample_count,
                          sample_duration_s=self.sample_duration_s, manual_ranges=self.manual_ranges)

    def _run_process(self, cmd: list[str], *, label: str):
        return self._process_runner.run(cmd, label=label)

    def _video_args(self, run):
        return self._service.video_args(run)

    def _encode_segment(self, input_path: str, output_path: str, run, segment) -> None:
        self._service.encode_segment(input_path, output_path, run, segment)

    def _probe_output(self, output_path: str) -> dict:
        return self._service.probe_output(output_path)

    def _analyze_result(self, input_path: str, output_path: str, run, segment):
        return self._service.analyze_result(input_path, output_path, run, segment)

    def _metric_filter(self, metric: str, width: int, height: int) -> str:
        return QualityMetricsService.encoded_filter(metric, width, height)

    def _measure_ssim(self, input_path: str, output_path: str, segment, width: int, height: int, notes: list[str]):
        return self._metrics.measure_encoded(metric="ssim", input_path=input_path, output_path=output_path,
            start_s=segment.start_s, duration_s=segment.duration_s, width=width, height=height, label="SSIM", notes=notes)

    def _measure_vmaf(self, input_path: str, output_path: str, segment, width: int, height: int, notes: list[str]):
        return self._metrics.measure_encoded(metric="libvmaf", input_path=input_path, output_path=output_path,
            start_s=segment.start_s, duration_s=segment.duration_s, width=width, height=height, label="VMAF", notes=notes)

    def _log_result(self, result) -> None:
        self._service.log_result(result)
