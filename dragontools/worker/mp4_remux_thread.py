from __future__ import annotations

import traceback
from pathlib import Path

from PyQt6.QtCore import pyqtSignal

from .base_worker import BaseWorker
from ..core.logger import create_worker_logger
from ..core.media_analyzer import analyze_media
from ..core.paths import get_tool_paths
from ..core.sidecar_transaction import SidecarCommitTransaction
from ..core.timeout_settings import get_timeout
from ..rules.rule_loader import load_subtitle_rules
from .mp4_remux_file_service import MP4RemuxFileService
from .mp4_remux_plan import MP4RemuxPlanner, resolve_mp4_output_path
from .mp4_remux_sidecars import MP4RemuxSidecarService
from .subtitle_sidecar_service import SubtitleExportResult
from .tool_runner import run_tool


class _UserAbortError(RuntimeError):
    """Interner Marker für benutzerinitiierte Abbrüche während ffmpeg läuft."""


class MP4RemuxThread(BaseWorker):
    """QThread-Orchestrator für normalen MP4-Remux ohne DV/Reencode."""

    log_line = pyqtSignal(str)
    progress = pyqtSignal(int)
    file_progress = pyqtSignal(str, int, object)
    file_result = pyqtSignal(str, bool, str)
    finished = pyqtSignal()

    def __init__(
        self,
        files: list[str] | None = None,
        output_dir: str | None = None,
        tools=None,
        apply_audio_rules: bool = True,
        export_subtitles: bool = True,
        ignore_subtitles: bool = False,
        subtitle_rules: dict | None = None,
        faststart: bool = True,
        overwrite_original: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.files = [str(Path(path).resolve()) for path in (files or [])]
        self.output_dir = output_dir
        self.tools = tools or get_tool_paths()
        self.apply_audio_rules = apply_audio_rules
        self.export_subtitles = export_subtitles
        self.ignore_subtitles = ignore_subtitles
        self.subtitle_rules = dict(subtitle_rules or load_subtitle_rules(default={}))
        self.faststart = faststart
        self.overwrite_original = overwrite_original
        self._current_idx = 0
        self._logger = create_worker_logger(gui_callback=self.log_line.emit)
        self.log_file_path = str(self._logger.log_file) if self._logger.log_file else None

    def run(self) -> None:
        total = len(self.files)
        self.progress.emit(0)
        self._logger.header([], "mp4_remux", total, "mp4_remux", None, "copy")
        try:
            for index, path in enumerate(self.files, start=1):
                if self.abort_requested:
                    self._log("MP4-Remux abgebrochen.", "warn")
                    break
                self._current_idx = index
                self.file_progress.emit(path, 0, None)
                try:
                    output_path, warning = resolve_mp4_output_path(
                        path,
                        output_dir=self.output_dir,
                        overwrite_original=self.overwrite_original,
                    )
                    if warning:
                        self._log(warning, "warn")
                    self._remux_file(path, str(output_path))
                except Exception as exc:
                    self._log(f"Unbehandelte Ausnahme bei {Path(path).name}", "error")
                    self._log(traceback.format_exc(), "error")
                    self.file_result.emit(path, False, str(exc))
                self.progress.emit(int(index / max(total, 1) * 100))
        finally:
            self.current_process = None
            self.finished.emit()

    def _planner(self) -> MP4RemuxPlanner:
        return MP4RemuxPlanner(
            ffmpeg_path=self.tools.ffmpeg,
            apply_audio_rules=self.apply_audio_rules,
            export_subtitles=self.export_subtitles,
            ignore_subtitles=self.ignore_subtitles,
            subtitle_rules=self.subtitle_rules,
            faststart=self.faststart,
            log=self._log,
            log_audio=self._logger.audio,
        )

    def _sidecar_service(self) -> MP4RemuxSidecarService:
        return MP4RemuxSidecarService(
            ffmpeg_path=self.tools.ffmpeg,
            subtitle_rules=self.subtitle_rules,
            log=self._log,
            abort_check=lambda: self.abort_requested,
            worker=self,
        )

    # Kompatibilitätswrapper: bestehende Tests/Plugins monkeypatchen diese APIs.
    def _is_mp4_video_compatible(self, media_info) -> tuple[bool, str]:
        return self._planner().video_compatibility(media_info)

    def _build_audio_plan(self, media_info):
        return self._planner().build_audio_plan(media_info)

    def _build_audio_args(self, plan) -> list[str]:
        return self._planner().build_audio_args(plan)

    def _extract_external_subtitles(
        self,
        input_path: str,
        out_base: str,
        media_info=None,
    ) -> SubtitleExportResult:
        media = media_info if media_info is not None else analyze_media(input_path, self.tools)
        return self._sidecar_service().export(input_path, out_base, media_info=media)

    def _cleanup_generated_sidecars(self, paths: list[str] | tuple[str, ...]) -> None:
        self._sidecar_service().cleanup_generated(paths)

    def _commit_sidecars(
        self,
        paths: list[str],
        *,
        source_base: Path,
        destination_base: Path,
        video_staging: Path,
        video_destination: Path,
        video_committed: bool = False,
    ) -> SidecarCommitTransaction | None:
        return self._sidecar_service().commit(
            paths,
            source_base=source_base,
            destination_base=destination_base,
            video_staging=video_staging,
            video_destination=video_destination,
            video_committed=video_committed,
        )

    def _run_ffmpeg_with_progress(self, cmd: list[str], duration_s: float, path: str) -> int:
        total_us = max(1, int(duration_s * 1_000_000)) if duration_s > 0 else 0
        full = cmd[:-1] + ["-progress", "pipe:1", "-nostats", cmd[-1]]

        def progress_line(raw: str) -> None:
            line = raw.strip()
            if line.startswith("out_time_ms=") and total_us > 0:
                try:
                    out_us = int(line.split("=", 1)[1].strip())
                    pct = max(0, min(100, int(out_us / total_us * 100)))
                    self.file_progress.emit(path, pct, None)
                except (TypeError, ValueError):
                    return
            elif line == "progress=end":
                self.file_progress.emit(path, 100, None)

        result = run_tool(
            full,
            label="MP4-Remux ffmpeg",
            timeout_s=get_timeout("worker_media_process"),
            timeout_mode="inactivity",
            worker=self,
            log=self._log,
            stdout_line=progress_line,
        )
        if result.aborted:
            raise _UserAbortError("Abgebrochen")
        if result.timed_out:
            raise RuntimeError("ffmpeg wurde wegen Inaktivitäts-Timeout abgebrochen.")
        if not result.ok:
            raise RuntimeError(result.tail(12) or f"ffmpeg return code {result.returncode}")
        return result.returncode

    def _remux_file(self, input_path: str, output_path: str) -> bool:
        media_info = analyze_media(input_path, self.tools)
        service = MP4RemuxFileService(
            planner=self._planner(),
            logger=self._logger,
            log=self._log,
            run_ffmpeg=self._run_ffmpeg_with_progress,
            export_sidecars=self._extract_external_subtitles,
            commit_sidecars=self._commit_sidecars,
            cleanup_sidecars=self._cleanup_generated_sidecars,
            abort_requested=lambda: self.abort_requested,
            emit_file_result=self.file_result.emit,
            emit_file_progress=self.file_progress.emit,
            export_subtitles=self.export_subtitles,
            ignore_subtitles=self.ignore_subtitles,
        )
        return service.remux(
            input_path,
            output_path,
            media_info,
            current_index=self._current_idx,
            total_files=len(self.files),
            user_abort_error=_UserAbortError,
        )
