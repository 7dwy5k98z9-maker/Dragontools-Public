# -*- coding: utf-8 -*-
from __future__ import annotations

import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Callable

from .duration_remux_service import DurationRemuxService
from .duration_repair_archive import DurationRepairArchive, format_duration as _fmt_duration, unique_archive_path as _unique_archive_path
from .duration_repair_commands import _command_arg_after, _setts_filter_for_fps
from .duration_repair_models import (
    DurationRepairOutcome,
    MediaTimingInfo,
    TimestampRepairResult,
    calculate_expected_duration,
    detect_timestamp_problem,
    duration_close as _duration_close,
)
from .duration_repair_orchestrator import DurationRepairOrchestrator
from .duration_repair_policy import can_repair_duration, mark_duration_repair_failed
from .duration_repair_runtime import DurationRepairRuntime
from .duration_repair_validation import validate_timestamp_repair as _validate_timestamp_repair
from .duration_timing_analyzer import MediaTimingAnalyzer
from .duration_timestamp_service import TimestampRepairService
from .tool_runner import ToolRunResult, run_tool
from .workflow_engine import WorkflowVerifyResult


class DurationRepairService:
    """Compatibility facade for lossless duration repair services."""

    def __init__(
        self,
        *,
        mkvmerge_path: str,
        output_verifier,
        mp4box_path: str = "",
        log: Callable[[str, str], None],
        ffmpeg_path: str = "",
        ffprobe_path: str = "",
        mediainfo_path: str = "",
        normal_remux_enabled: bool = True,
        timestamp_repair_enabled: bool = True,
        worker=None,
        run_tool_fn: Callable[..., ToolRunResult] | None = None,
    ) -> None:
        resolved_ffprobe = str(ffprobe_path or getattr(output_verifier, "_ffprobe_path", "") or "")
        self._normal_remux_enabled = bool(normal_remux_enabled)
        self._timestamp_repair_enabled = bool(timestamp_repair_enabled)
        self._runtime = DurationRepairRuntime(
            mkvmerge_path=str(mkvmerge_path or ""),
            mp4box_path=str(mp4box_path or ""),
            ffmpeg_path=str(ffmpeg_path or ""),
            ffprobe_path=resolved_ffprobe,
            mediainfo_path=str(mediainfo_path or ""),
            output_verifier=output_verifier,
            log=log,
            worker=worker,
            run_tool_fn=run_tool_fn or run_tool,
        )
        self._timing_analyzer = MediaTimingAnalyzer(
            ffprobe_path=self._runtime.ffprobe_path,
            mediainfo_path=self._runtime.mediainfo_path,
            run_command=subprocess.run,
        )
        self._remux_service = DurationRemuxService(self._runtime)
        self._timestamp_service = TimestampRepairService(self._runtime, self._timing_analyzer)
        self._archive_service = DurationRepairArchive(self._runtime)
        self._orchestrator = DurationRepairOrchestrator(
            remux_service=self._remux_service,
            timestamp_service=self._timestamp_service,
            archive=self._archive_service,
            log=self._runtime.log,
        )

        # Compatibility aliases used by older internal code/tests.
        self._mkvmerge_path = self._runtime.mkvmerge_path
        self._mp4box_path = self._runtime.mp4box_path
        self._output_verifier = self._runtime.output_verifier
        self._log = self._runtime.log
        self._ffmpeg_path = self._runtime.ffmpeg_path
        self._ffprobe_path = self._runtime.ffprobe_path
        self._mediainfo_path = self._runtime.mediainfo_path
        self._worker = self._runtime.worker
        self._run_tool = self._runtime.run_tool_fn

    def can_repair(self, *, output_path: str | None, container: str, verify_result: WorkflowVerifyResult) -> bool:
        return can_repair_duration(
            output_path=output_path,
            container=container,
            verify_result=verify_result,
            normal_remux_enabled=self._normal_remux_enabled,
            timestamp_repair_enabled=self._timestamp_repair_enabled,
        )

    def repair(
        self,
        *,
        output_path: str | None,
        base_dir: Path | None,
        container: str,
        expected_duration_ms: int | None,
        source_has_audio: bool,
        initial_result: WorkflowVerifyResult,
        expected_contract=None,
        verified_hdr10plus: bool = False,
        verified_dolby_vision: bool = False,
    ) -> DurationRepairOutcome:
        if not self.can_repair(output_path=output_path, container=container, verify_result=initial_result):
            return DurationRepairOutcome(verify_result=initial_result)
        return self._orchestrator.repair(
            output_path=str(output_path),
            base_dir=base_dir,
            container=container,
            expected_duration_ms=expected_duration_ms,
            source_has_audio=source_has_audio,
            initial_result=initial_result,
            expected_contract=expected_contract,
            verified_hdr10plus=verified_hdr10plus,
            verified_dolby_vision=verified_dolby_vision,
            normal_remux_enabled=self._normal_remux_enabled,
            timestamp_repair_enabled=self._timestamp_repair_enabled,
        )

    @staticmethod
    def _mark_failed_result(final_result, messages: list[str]) -> None:
        mark_duration_repair_failed(final_result, messages)

    # Compatibility surface -------------------------------------------------
    def attempt_normal_remux(self, **kwargs):
        return self._remux_service.attempt(**kwargs)

    def _normal_remux_tool(self, container: str) -> tuple[str, str]:
        return self._remux_service.normal_remux_tool(container)

    def _try_timestamp_repair(self, **kwargs) -> TimestampRepairResult:
        return self._timestamp_service.try_repair(**kwargs)

    def get_media_timing_info(self, path: str, *, expected_duration_s: float | None = None) -> MediaTimingInfo:
        return self._timestamp_service.get_media_timing_info(path, expected_duration_s=expected_duration_s)

    def repair_video_timestamps(self, **kwargs) -> TimestampRepairResult:
        return self._timestamp_service.repair_video_timestamps(**kwargs)

    def validate_timestamp_repair(
        self,
        *,
        before: MediaTimingInfo,
        repaired: MediaTimingInfo,
        verify_result: WorkflowVerifyResult,
        expected_duration_ms: int | None,
        source_has_audio: bool,
    ) -> tuple[bool, list[str]]:
        return _validate_timestamp_repair(
            before=before,
            repaired=repaired,
            verify_result=verify_result,
            expected_duration_ms=expected_duration_ms,
            source_has_audio=source_has_audio,
        )

    def _build_timestamp_repair_command(
        self,
        source: Path,
        target: Path,
        fps: Fraction,
        *,
        container: str | None = None,
    ) -> list[str]:
        return self._timestamp_service.build_timestamp_repair_command(source, target, fps, container=container)

    def _run_ffprobe_json(self, path: str, *, count_frames: bool = False) -> dict:
        return self._timing_analyzer.run_ffprobe_json(path, count_frames=count_frames)

    def _run_mediainfo_json(self, path: str) -> dict:
        return self._timing_analyzer.run_mediainfo_json(path)

    def _apply_ffprobe_timing(self, info: MediaTimingInfo, data: dict) -> None:
        self._timing_analyzer.apply_ffprobe_timing(info, data)

    def _apply_mediainfo_timing(self, info: MediaTimingInfo, data: dict) -> None:
        self._timing_analyzer.apply_mediainfo_timing(info, data)

    def _derive_frame_rate_from_source_duration(self, info: MediaTimingInfo, expected_duration_s: float | None) -> None:
        self._timing_analyzer.derive_frame_rate_from_source_duration(info, expected_duration_s)

    def _infer_frame_rate_mode(self, info: MediaTimingInfo) -> str:
        return self._timing_analyzer.infer_frame_rate_mode(info)

    def _timing_summary(self, info: MediaTimingInfo) -> list[str]:
        return self._timestamp_service.timing_summary(info)

    def _ffmpeg_supports_setts(self) -> bool:
        return self._timestamp_service.ffmpeg_supports_setts()

    def _archive_output(self, output_path: Path, base_dir: Path | None) -> str | None:
        return self._archive_service.archive(output_path, base_dir)

    def _safe_unlink(self, path: Path) -> None:
        self._runtime.safe_unlink(path)
