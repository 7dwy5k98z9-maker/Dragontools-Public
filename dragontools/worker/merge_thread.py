from __future__ import annotations

import traceback
from pathlib import Path

from PyQt6.QtCore import pyqtSignal

from ..core.logger import create_worker_logger
from ..core.paths import get_tool_paths
from .base_worker import BaseWorker
from .merge_analysis import MergeAnalysisMixin
from .merge_common import (
    MergeUserAbortError,
    audio_signature,
    container_from_format_name,
    container_from_path,
    parse_fps,
    subtitle_signature,
)
from .merge_executor import MergeExecutorMixin
from .merge_plan import MergePlanMixin

# Kompatibilitätsnamen für bestehende interne Imports/Tests.
_UserAbortError = MergeUserAbortError
_container_from_path = container_from_path
_container_from_format_name = container_from_format_name
_parse_fps = parse_fps
_audio_signature = audio_signature
_subtitle_signature = subtitle_signature


class MergeThread(MergeAnalysisMixin, MergePlanMixin, MergeExecutorMixin, BaseWorker):
    """Thread-Lifecycle für konservatives lossless Merge."""

    SUPPORTED_MODES = {"lossless", "check_only"}

    log_line = pyqtSignal(str)
    progress = pyqtSignal(int)
    file_progress = pyqtSignal(str, int, object)
    file_result = pyqtSignal(str, bool, str)
    finished = pyqtSignal()

    def __init__(
        self,
        files: list[str] | None = None,
        output_path: str | None = None,
        tools=None,
        mode: str = "lossless",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.files = [str(Path(path).resolve()) for path in (files or [])]
        self.output_path = str(Path(output_path).resolve()) if output_path else None
        self.tools = tools or get_tool_paths()
        self.mode = mode
        self._logger = create_worker_logger(gui_callback=self.log_line.emit)
        self.log_file_path = str(self._logger.log_file) if self._logger.log_file else None

    def run(self) -> None:
        self.progress.emit(0)
        self._logger.header([], "merge", len(self.files), "merge", None, self.mode)
        try:
            validation_error = self._validate_request()
            if validation_error:
                self._emit_rejected(validation_error)
                return

            infos = self._analyze_inputs(self.files)
            if self.abort_requested:
                self.file_result.emit(self.output_path, False, "Abgebrochen")
                return

            plan = self._build_merge_plan(infos, self.output_path, self.mode)
            self.file_progress.emit(self.output_path, 35, plan)
            self.progress.emit(35)

            if self.mode == "check_only":
                reason_text = "; ".join(plan["reasons"]) or "Lossless Merge möglich."
                self.progress.emit(100)
                self.file_result.emit(
                    self.output_path,
                    bool(plan["lossless_possible"]),
                    reason_text,
                )
                return

            if not plan["lossless_possible"]:
                reason_text = "; ".join(plan["reasons"]) or "Lossless Merge nicht möglich."
                self._log(f"Lossless Merge abgelehnt: {reason_text}", "warn")
                self.progress.emit(100)
                self.file_result.emit(self.output_path, False, reason_text)
                return

            ok = self._run_lossless_merge(plan)
            if self.abort_requested:
                self.file_result.emit(self.output_path, False, "Abgebrochen")
                return

            self.progress.emit(100)
            if ok:
                self.file_result.emit(self.output_path, True, self.output_path)
            else:
                self.file_result.emit(
                    self.output_path,
                    False,
                    "Lossless Merge fehlgeschlagen",
                )
        except MergeUserAbortError:
            self.file_result.emit(self.output_path or "", False, "Abgebrochen")
        except Exception as exc:
            self._log("Unbehandelte Ausnahme im MergeThread.", "error")
            self._log(traceback.format_exc(), "error")
            self.file_result.emit(self.output_path or "", False, str(exc))
        finally:
            self.current_process = None
            self.finished.emit()

    def _validate_request(self) -> str:
        if self.mode not in self.SUPPORTED_MODES:
            return f"Merge-Modus '{self.mode}' wird nicht unterstützt."
        if len(self.files) < 2:
            return "Für Merge werden mindestens zwei Eingabedateien benötigt."
        if not self.output_path:
            return "Keine Zieldatei gesetzt."
        return ""

    def _emit_rejected(self, message: str) -> None:
        self._log(message, "error")
        self.file_result.emit(self.output_path or "", False, message)
        self.progress.emit(100)
