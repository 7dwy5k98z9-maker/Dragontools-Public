# -*- coding: utf-8 -*-
"""Qt lifecycle facade for AudioMux jobs."""
from __future__ import annotations

import subprocess
import threading
import traceback
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from ..core.tool_paths import get_tool_paths
from ..core.output_replace import commit_staged_output  # compatibility re-export; commit lives in audio_mux_job
from ..core.timeout_settings import get_timeout
from .audio_mux_job import AudioMuxJobRunner
from .audio_mux_output_verifier import AudioMuxOutputVerifier
from .audio_mux_plan_service import AudioMuxPlanService
from .process_control import terminate_process_tree
from .tool_runner import run_tool


class AudioMuxThread(QThread):
    progress_total = pyqtSignal(int)
    progress_file = pyqtSignal(str, int)
    log_line = pyqtSignal(str)
    file_result = pyqtSignal(str, bool, str)

    def __init__(self, files: list[str], overwrite_original: bool = False, parent=None):
        super().__init__(parent)
        self.files = [str(Path(f).resolve()) for f in files]
        self.overwrite_original = overwrite_original
        self.abort_requested = False
        self.abort_type: str | None = None
        self.current_process: subprocess.Popen[str] | None = None
        self._process_lock = threading.Lock()
        self.tools = get_tool_paths()
        self._plan_service = AudioMuxPlanService(tools=self.tools)
        self._output_verifier = AudioMuxOutputVerifier(ffprobe_path=str(self.tools.ffprobe))
        self._job_runner = AudioMuxJobRunner(self, planner=self._plan_service, verifier=self._output_verifier)

    def request_abort(self, mode: str = "sofort") -> None:
        self.abort_requested = True
        self.abort_type = mode
        if mode == "sofort":
            terminate_process_tree(
                self, self._process_lock,
                log=lambda msg, level="warn": self.log_line.emit(msg),
                attr_name="current_process", label="Audio-Mux",
            )

    def cancel(self) -> None:
        self.request_abort()

    def run(self) -> None:
        total, done = len(self.files), 0
        try:
            for path in self.files:
                if self.abort_requested:
                    self.log_line.emit("⚠️ Abbruch angefordert.")
                    break
                try:
                    self._process_file_safe(path)
                except Exception as exc:
                    self.log_line.emit(f"❌ Unbehandelte Ausnahme bei {Path(path).name}")
                    self.log_line.emit(traceback.format_exc())
                    self.file_result.emit(path, False, str(exc))
                done += 1
                self.progress_total.emit(int(done / max(total, 1) * 100))
        finally:
            self.current_process = None

    def run_ffmpeg_with_progress(self, cmd: list[str], duration_s: float, path: str) -> int:
        total_us = max(1, int(duration_s * 1_000_000)) if duration_s > 0 else 0
        full = cmd[:-1] + ["-progress", "pipe:1", "-nostats", cmd[-1]]
        def _progress_line(raw: str) -> None:
            line = raw.strip()
            if line.startswith("out_time_ms=") and total_us > 0:
                try:
                    out_us = int(line.split("=", 1)[1].strip())
                    self.progress_file.emit(path, max(0, min(100, int(out_us / total_us * 100))))
                except (TypeError, ValueError):
                    return
            elif line == "progress=end":
                self.progress_file.emit(path, 100)
        result = run_tool(
            full, label="Audio-Mux ffmpeg", timeout_s=get_timeout("worker_media_process"),
            timeout_mode="inactivity", worker=self,
            log=lambda msg, level="info": self.log_line.emit(msg), stdout_line=_progress_line,
        )
        if result.aborted:
            return result.returncode
        if result.timed_out:
            raise RuntimeError("ffmpeg wurde wegen Inaktivitäts-Timeout abgebrochen.")
        if not result.ok:
            raise RuntimeError(result.tail(12) or f"ffmpeg return code {result.returncode}")
        return result.returncode

    def _run_ffmpeg_with_progress(self, cmd: list[str], duration_s: float, path: str) -> int:
        return self.run_ffmpeg_with_progress(cmd, duration_s, path)

    def _process_file_safe(self, path: str) -> None:
        self._job_runner.run(path)

    # Compatibility delegates for tests/extensions that used the old helper surface.
    def _build_output_path(self, src: Path):
        return self._plan_service.build_output_path(src, self.overwrite_original)

    def _build_audio_plan(self, media_info):
        return self._plan_service.build_audio_plan(media_info)

    def _build_ffmpeg_cmd(self, src: str, out: str, plan):
        return self._plan_service.build_ffmpeg_cmd(src, out, plan)

    def _log_audio_decisions(self, plan) -> None:
        self._job_runner.log_audio_decisions(plan)
