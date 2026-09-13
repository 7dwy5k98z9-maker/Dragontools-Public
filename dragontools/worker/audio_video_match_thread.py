# -*- coding: utf-8 -*-
"""Thin Qt adapter for the audio/video match service."""
from __future__ import annotations

import subprocess
import threading
import traceback

from PyQt6.QtCore import QThread, pyqtSignal

from ..core.audio_video_matcher import CutMatchResult, TimeMappingResult
from ..core.tool_paths import get_tool_paths
from .audio_video_match_contracts import AudioVideoMatchCallbacks, AudioVideoMatchRequest
from .audio_video_match_service import AudioVideoMatchService
from .process_control import terminate_process_tree


class AudioVideoMatchThread(QThread):
    log_line = pyqtSignal(str)
    progress = pyqtSignal(int)
    analysis_ready = pyqtSignal(object)
    cuts_ready = pyqtSignal(object)
    plan_ready = pyqtSignal(object)
    result_ready = pyqtSignal(str)
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(
        self,
        operation: str,
        *,
        source_path: str,
        target_path: str,
        output_path: str = "",
        audio_stream_index: int | None = None,
        mapping_result: TimeMappingResult | None = None,
        cut_ranges_text: str = "",
        cut_results: list[CutMatchResult] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.request = AudioVideoMatchRequest.create(
            operation,
            source_path=source_path,
            target_path=target_path,
            output_path=output_path,
            audio_stream_index=audio_stream_index,
            mapping_result=mapping_result,
            cut_ranges_text=cut_ranges_text,
            cut_results=cut_results,
        )
        # Keep the historical public attributes while callers migrate to request.
        self.operation = self.request.operation
        self.source_path = self.request.source_path
        self.target_path = self.request.target_path
        self.output_path = self.request.output_path
        self.audio_stream_index = self.request.audio_stream_index
        self.mapping_result = self.request.mapping_result
        self.cut_ranges_text = self.request.cut_ranges_text
        self.cut_results = list(self.request.cut_results)
        self.tools = get_tool_paths()
        self.current_process: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self.abort_requested = False
        self.abort_type: str | None = None

    def request_abort(self, mode: str = "sofort") -> None:
        self.abort_requested = True
        self.abort_type = mode
        if mode == "sofort":
            terminate_process_tree(
                self,
                self._lock,
                log=self._log,
                attr_name="current_process",
                label="Audio-Video-Matcher",
            )

    def cancel(self) -> None:
        self.request_abort("sofort")

    def run(self) -> None:
        try:
            service = AudioVideoMatchService(
                tools=self.tools,
                callbacks=AudioVideoMatchCallbacks(
                    log_line=self.log_line.emit,
                    progress=self.progress.emit,
                    analysis_ready=self.analysis_ready.emit,
                    cuts_ready=self.cuts_ready.emit,
                    plan_ready=self.plan_ready.emit,
                    result_ready=self.result_ready.emit,
                ),
                process_worker=self,
                is_aborted=lambda: self.abort_requested,
            )
            service.execute(self.request)
        except Exception as exc:
            # Thread boundary: unexpected failures must be surfaced to the GUI,
            # not swallowed.  The traceback is deliberately preserved in logs.
            self.log_line.emit("❌ Unbehandelte Ausnahme im Audio-Video-Matcher:")
            self.log_line.emit(traceback.format_exc())
            self.error.emit(str(exc))
        finally:
            self.current_process = None
            self.finished.emit()

    def _log(self, message: str, severity: str = "info") -> None:
        prefix = {"error": "❌", "warn": "⚠️", "info": "ℹ️"}.get(severity, "ℹ️")
        self.log_line.emit(f"{prefix} {message}")


__all__ = ["AudioVideoMatchThread"]
