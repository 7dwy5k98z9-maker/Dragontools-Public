from __future__ import annotations

import subprocess
import threading
import traceback
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from ..core.logger import create_worker_logger
from ..core.tool_paths import get_tool_paths
from .iso_disc_inspector import (
    ISODiscInspector,
    _format_size,
    _parse_duration_to_seconds,
    _parse_size_to_bytes,
    _quote_concat_path,
    _safe_name,
)
from .iso_ffmpeg_fallback_service import ISOFFmpegFallbackService
from .iso_makemkv_service import ISOMakeMKVService, tool_exists as _tool_exists
from .iso_models import ISOUserAbortError
from .iso_selection import choose_auto_titles
from .process_control import terminate_process_tree
from .iso_input_processor import ISOInputProcessor
from .iso_processor_host_mixin import ISOProcessorHostMixin

# Historical internal name kept for tests/callers that may catch it.
_UserAbortError = ISOUserAbortError


class ISOThread(ISOProcessorHostMixin, QThread):
    """Qt lifecycle/orchestration for conservative ISO/disc extraction.

    MakeMKV parsing/extraction, disc inspection and the FFmpeg fallback are
    delegated to Qt-independent services. The thread owns only lifecycle,
    signals, user cancellation and per-input orchestration.
    """

    log_line = pyqtSignal(str)
    progress = pyqtSignal(int)
    file_progress = pyqtSignal(str, int, object)
    file_result = pyqtSignal(str, bool, str)
    files_extracted = pyqtSignal(list)
    finished = pyqtSignal()

    def __init__(
        self,
        inputs: list[str] | None = None,
        output_dir: str | None = None,
        tools=None,
        selected_titles: dict[str, list[int]] | None = None,
        auto_main_title: bool = True,
        auto_series_disc: bool = True,
        handoff_to_converter: bool = False,
        scan_only: bool = False,
        ffmpeg_fallback: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.inputs = inputs or []
        self.output_dir = output_dir
        self.tools = tools or get_tool_paths()
        self.selected_titles = selected_titles or {}
        self.auto_main_title = auto_main_title
        self.auto_series_disc = auto_series_disc
        self.handoff_to_converter = handoff_to_converter
        self.scan_only = scan_only
        self.ffmpeg_fallback = ffmpeg_fallback
        self.abort_requested = False
        self.abort_type: str | None = None
        self.current_process: subprocess.Popen[str] | None = None
        self._process_lock = threading.Lock()
        self._last_scan_error: str | None = None
        self._last_ffmpeg_fallback_error: str | None = None
        self._extracted_files: list[str] = []

        self._logger = create_worker_logger(gui_callback=self.log_line.emit)
        self.log_file_path = str(self._logger.log_file) if self._logger.log_file else None
        self._current_idx = 0

        self._disc_inspector = ISODiscInspector(log=self._log)
        self._makemkv_service = ISOMakeMKVService(
            tools=self.tools,
            inspector=self._disc_inspector,
            worker=self,
            log=self._log,
            progress=self.file_progress.emit,
        )
        self._ffmpeg_service = ISOFFmpegFallbackService(
            tools=self.tools,
            inspector=self._disc_inspector,
            worker=self,
            log=self._log,
            progress=self.file_progress.emit,
        )
        self._input_processor = ISOInputProcessor(self)

    def _log(self, message: str, level: str = "info") -> None:
        if level == "error":
            self._logger.error(message)
        elif level == "warn":
            self._logger.warn(message)
        elif level == "success":
            self._logger.success(message)
        else:
            self._logger.info(message)

    def request_abort(self, mode: str = "sofort") -> None:
        self.abort_requested = True
        self.abort_type = mode
        if mode == "sofort":
            terminate_process_tree(
                self,
                self._process_lock,
                log=self._log,
                attr_name="current_process",
                label="ISO-Tool",
            )
        self._log("⚠️ Abbruch angefordert.", "warn")

    def cancel(self) -> None:
        self.request_abort()

    def run(self) -> None:
        total = len(self.inputs)
        self._extracted_files = []
        self.progress.emit(0)
        try:
            if not self._makemkv_available():
                if not self.ffmpeg_fallback:
                    self._ensure_tool()
                self._log(
                    "⚠️ MakeMKV CLI nicht verfügbar. "
                    "ISO-Verarbeitung versucht den FFmpeg-Fallback, sofern möglich.",
                    "warn",
                )
            for index, path in enumerate(self.inputs, start=1):
                self._current_idx = index
                self.file_progress.emit(path, 0, None)
                if self.abort_requested:
                    self.file_result.emit(path, False, "Abgebrochen")
                    break
                try:
                    self._process_input(path, total)
                except _UserAbortError:
                    self.file_result.emit(path, False, "Abgebrochen")
                    break
                except Exception as exc:
                    self._log(f"❌ Unbehandelte Ausnahme bei {_safe_name(path)}")
                    self._log(traceback.format_exc())
                    self.file_result.emit(path, False, str(exc))
                finally:
                    self.progress.emit(int(index / max(total, 1) * 100))
        except Exception as exc:
            self._log(f"❌ {exc}")
            for path in self.inputs:
                self.file_result.emit(path, False, str(exc))
        finally:
            self.current_process = None
            self.files_extracted.emit(list(self._extracted_files))
            self.finished.emit()

    def _process_input(self, path: str, total: int) -> None:
        self._input_processor.process(path, total)

    def select_auto_titles(self, titles: list[dict]) -> tuple[list[int], bool]:
        """Resolve automatic title selection from the thread-owned user options."""
        return choose_auto_titles(titles, detect_series_disc=self.auto_series_disc)

    # --- Compatibility/delegation surface ------------------------------------

    def _ensure_tool(self) -> str:
        return self._makemkv_service.ensure_tool()

    def _makemkv_available(self) -> bool:
        return self._makemkv_service.available()

    def _ensure_ffmpeg(self) -> str:
        return self._ffmpeg_service.ensure_ffmpeg()

    def _makemkv_source(self, path: str) -> str:
        return self._disc_inspector.makemkv_source(path)

    def _disc_root_for_makemkv(self, path: Path) -> Path:
        return self._disc_inspector.disc_root_for_makemkv(path)

    def _run_makemkv(self, args: list[str], progress_path: str | None = None) -> tuple[int, list[str]]:
        return self._makemkv_service.run(args, progress_path=progress_path)

    def _detect_iso_type(self, path: str) -> str:
        return self._disc_inspector.detect_iso_type(path)

    def _scan_titles(self, path: str) -> list[dict]:
        result = self._makemkv_service.scan_titles(path, run_makemkv=self._run_makemkv)
        self._last_scan_error = result.error
        return result.titles

    def _extract_titles(self, path: str, title_ids: list[int], output_dir: str) -> bool:
        result = self._makemkv_service.extract_titles(
            path,
            title_ids,
            output_dir,
            run_makemkv=self._run_makemkv,
        )
        if result.extracted_files:
            self._extracted_files.extend(result.extracted_files)
        return result.ok

    def _scan_ffmpeg_fallback_titles(self, path: str) -> list[dict]:
        titles, error = self._disc_inspector.fallback_titles(path)
        if error:
            self._last_ffmpeg_fallback_error = error
        return titles

    def _ffmpeg_fallback_candidate(self, path: str) -> dict | None:
        candidate, error = self._disc_inspector.ffmpeg_fallback_candidate(path)
        if error:
            self._last_ffmpeg_fallback_error = error
        return candidate

    def _dvd_vob_candidate(self, dvd_dir: Path) -> dict | None:
        return self._disc_inspector.dvd_vob_candidate(dvd_dir)

    def _extract_with_ffmpeg_fallback(self, path: str, output_dir: str) -> bool:
        self._last_ffmpeg_fallback_error = None
        result = self._ffmpeg_service.extract(
            path,
            output_dir,
            run_ffmpeg=self._run_ffmpeg_fallback,
        )
        self._last_ffmpeg_fallback_error = result.error
        if result.extracted_files:
            self._extracted_files.extend(result.extracted_files)
        return result.ok

    def _run_ffmpeg_fallback(self, cmd: list[str], progress_path: str | None = None) -> tuple[int, list[str]]:
        return self._ffmpeg_service.run(cmd, progress_path=progress_path)

    def _unique_fallback_output(self, input_path: str, output_dir: Path) -> Path:
        return self._disc_inspector.unique_fallback_output(input_path, output_dir)
