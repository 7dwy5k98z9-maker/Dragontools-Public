# -*- coding: utf-8 -*-
from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from uuid import uuid4

from ..core.process_runner import tool_available
from .duration_repair_commands import (
    build_genpts_repair_command,
    build_timestamp_repair_command,
    command_arg_after,
)
from .duration_repair_models import MediaTimingInfo, TimestampRepairResult, detect_timestamp_problem
from .duration_repair_runtime import DurationRepairRuntime
from .duration_repair_stream_guard import RepairStreamGuard, StreamInventory
from .duration_timestamp_candidate_service import TimestampCandidateService
from .duration_timing_analyzer import MediaTimingAnalyzer, _fps_label
from .workflow_engine import WorkflowVerifyResult


class TimestampRepairService:
    """Stage 2: diagnose and rebuild damaged video timestamps without re-encoding."""

    def __init__(self, runtime: DurationRepairRuntime, timing_analyzer: MediaTimingAnalyzer) -> None:
        self._runtime = runtime
        self._timing_analyzer = timing_analyzer
        self._setts_supported: bool | None = None
        self._stream_guard = RepairStreamGuard(
            timing_analyzer=timing_analyzer,
            ffprobe_path=runtime.ffprobe_path,
            mediainfo_path=runtime.mediainfo_path,
            log=runtime.log,
        )
        self._candidate_service = TimestampCandidateService(runtime, timing_analyzer, self._stream_guard)

    def try_repair(
        self,
        *,
        out: Path,
        container: str,
        base_dir: Path | None = None,
        expected_duration_ms: int | None,
        expected_duration_s: float | None,
        source_has_audio: bool,
        reference_result: WorkflowVerifyResult,
        expected_contract=None,
        verified_hdr10plus: bool = False,
        verified_dolby_vision: bool = False,
    ) -> TimestampRepairResult:
        if not tool_available(self._runtime.ffprobe_path):
            reason = "ffprobe wurde nicht gefunden - Timestamp-Prüfung nicht möglich."
            self._runtime.log(f"❌ {reason}", "error")
            return TimestampRepairResult(verify_result=reference_result, reason=reason)

        self._runtime.log("ℹ️ [Reparatur 2/2] Timestamp-Prüfung gestartet.", "info")
        before = self.get_media_timing_info(str(out), expected_duration_s=expected_duration_s)
        summary = self.timing_summary(before)
        for line in summary:
            self._runtime.log(f"   {line}", "info")

        problem = detect_timestamp_problem(before, expected_duration_s=expected_duration_s)
        if not problem.should_repair:
            self._runtime.log(f"⚠️ Keine sichere Timestamp-Reparatur: {problem.reason}", "warn")
            return TimestampRepairResult(
                verify_result=reference_result,
                reason=f"Keine sichere Timestamp-Reparatur: {problem.reason}",
                timing_summary=summary,
            )

        self._runtime.log("⚠️ Extreme Abweichung im Videostream erkannt.", "warn")
        self._runtime.log("ℹ️ Starte verlustfreie Timestamp-Reparatur.", "info")
        if before.frame_rate is not None:
            self._runtime.log(f"   Rekonstruktionsrate: {_fps_label(before.frame_rate)} fps", "info")

        container_name = str(container or "").strip().lower().lstrip(".")
        availability_error = self._tool_availability_error(container_name)
        if availability_error:
            self._runtime.log(f"❌ {availability_error}", "error")
            return TimestampRepairResult(
                verify_result=reference_result,
                reason=availability_error,
                timing_summary=summary,
            )

        before_ffprobe, before_mediainfo = self._stream_guard.inspect_pair(str(out))
        self._log_reference_inventories(before_ffprobe, before_mediainfo)
        return self.repair_video_timestamps(
            out=out,
            container=container,
            base_dir=base_dir,
            expected_duration_ms=expected_duration_ms,
            source_has_audio=source_has_audio,
            before=before,
            timing_summary=summary,
            expected_contract=expected_contract,
            verified_hdr10plus=verified_hdr10plus,
            verified_dolby_vision=verified_dolby_vision,
            before_ffprobe=before_ffprobe,
            before_mediainfo=before_mediainfo,
        )

    def get_media_timing_info(self, path: str, *, expected_duration_s: float | None = None) -> MediaTimingInfo:
        return self._timing_analyzer.get_media_timing_info(path, expected_duration_s=expected_duration_s)

    def repair_video_timestamps(
        self,
        *,
        out: Path,
        container: str,
        base_dir: Path | None = None,
        expected_duration_ms: int | None,
        source_has_audio: bool,
        before: MediaTimingInfo,
        timing_summary: list[str],
        expected_contract=None,
        verified_hdr10plus: bool = False,
        verified_dolby_vision: bool = False,
        before_ffprobe: StreamInventory | None = None,
        before_mediainfo: StreamInventory | None = None,
    ) -> TimestampRepairResult:
        if before.frame_rate is None:
            return TimestampRepairResult(reason="Framerate fehlt.", timing_summary=timing_summary)
        if before_ffprobe is None or before_mediainfo is None:
            before_ffprobe, before_mediainfo = self._stream_guard.inspect_pair(str(out))

        container_name = str(container or "").strip().lower().lstrip(".")
        primary_is_genpts = False
        primary_tmp = out.with_name(f"{out.stem}.timestamp_fix_{uuid4().hex}{out.suffix}")
        if container_name == "mp4":
            primary_command = self.build_timestamp_repair_command(
                out, primary_tmp, before.frame_rate, container=container
            )
            self._runtime.log(f"   MP4Box CFR-Neuaufbau: {_fps_label(before.frame_rate)} fps", "info")
            primary_label = "MP4Box-Timestamp-Reparatur"
            primary_method = "MP4Box CFR-Neuaufbau"
        elif self.ffmpeg_supports_setts():
            primary_command = self.build_timestamp_repair_command(
                out, primary_tmp, before.frame_rate, container=container
            )
            self._runtime.log("   FFmpeg setts: " + command_arg_after(primary_command, "-bsf:v:0"), "info")
            primary_label = "FFmpeg-setts-Timestamp-Reparatur"
            primary_method = "FFmpeg setts"
        else:
            primary_is_genpts = True
            primary_tmp = out.with_name(f"{out.stem}.timestamp_genpts_{uuid4().hex}{out.suffix}")
            primary_command = build_genpts_repair_command(
                out, primary_tmp, ffmpeg_path=self._runtime.ffmpeg_path
            )
            self._runtime.log(
                "ℹ️ FFmpeg-setts ist nicht verfügbar; starte direkt den verlustfreien +genpts/+igndts-Fallback.",
                "info",
            )
            primary_label = "FFmpeg-+genpts+igndts-Timestamp-Reparatur"
            primary_method = "FFmpeg +genpts+igndts"

        fallback_tmp: Path | None = None
        try:
            result = self._attempt_candidate(
                out=out,
                tmp=primary_tmp,
                base_dir=base_dir,
                command=primary_command,
                label=primary_label,
                method=primary_method,
                container=container,
                before=before,
                before_ffprobe=before_ffprobe,
                before_mediainfo=before_mediainfo,
                expected_duration_ms=expected_duration_ms,
                source_has_audio=source_has_audio,
                timing_summary=timing_summary,
                expected_contract=expected_contract,
                verified_hdr10plus=verified_hdr10plus,
                verified_dolby_vision=verified_dolby_vision,
            )
            if (
                result.repaired
                or container_name != "mkv"
                or primary_is_genpts
                or not tool_available(self._runtime.ffmpeg_path)
            ):
                return result

            self._runtime.log(
                "ℹ️ Erste Timestamp-Reparatur wurde nicht akzeptiert. "
                "Starte verlustfreien FFmpeg-+genpts/+igndts-Fallback.",
                "info",
            )
            fallback_tmp = out.with_name(f"{out.stem}.timestamp_genpts_{uuid4().hex}{out.suffix}")
            fallback_command = build_genpts_repair_command(out, fallback_tmp, ffmpeg_path=self._runtime.ffmpeg_path)
            fallback = self._attempt_candidate(
                out=out,
                tmp=fallback_tmp,
                base_dir=base_dir,
                command=fallback_command,
                label="FFmpeg-+genpts+igndts-Timestamp-Reparatur",
                method="FFmpeg +genpts+igndts",
                container=container,
                before=before,
                before_ffprobe=before_ffprobe,
                before_mediainfo=before_mediainfo,
                expected_duration_ms=expected_duration_ms,
                source_has_audio=source_has_audio,
                timing_summary=timing_summary,
                expected_contract=expected_contract,
                verified_hdr10plus=verified_hdr10plus,
                verified_dolby_vision=verified_dolby_vision,
            )
            if not fallback.repaired and result.reason and result.reason not in fallback.reason:
                fallback.reason = f"{fallback.reason} Vorheriger Versuch: {result.reason}"
            return fallback
        except Exception as exc:
            self._runtime.safe_unlink(primary_tmp)
            if fallback_tmp is not None:
                self._runtime.safe_unlink(fallback_tmp)
            self._runtime.log(f"❌ Timestamp-Reparatur fehlgeschlagen: {exc}", "error")
            return TimestampRepairResult(
                attempted=True,
                reason=f"Timestamp-Reparatur fehlgeschlagen: {exc}",
                command=primary_command,
                timing_summary=timing_summary,
                retry_recommended=False,
            )

    def _attempt_candidate(self, **kwargs) -> TimestampRepairResult:
        return self._candidate_service.attempt(**kwargs)

    def build_timestamp_repair_command(
        self,
        source: Path,
        target: Path,
        fps: Fraction,
        *,
        container: str | None = None,
    ) -> list[str]:
        return build_timestamp_repair_command(
            source,
            target,
            fps,
            container=container,
            mp4box_path=self._runtime.mp4box_path,
            ffmpeg_path=self._runtime.ffmpeg_path,
        )

    def timing_summary(self, info: MediaTimingInfo) -> list[str]:
        from .duration_timing_analyzer import _derived_fps_suffix

        return [
            f"Containerdauer: {_fmt_duration(info.container_duration_s)}",
            f"Videodauer: {_fmt_duration(info.video_duration_s)}",
            f"Audiodauer: {_fmt_duration(info.audio_duration_s)}",
            f"Untertiteldauer: {_fmt_duration(info.subtitle_duration_s)}",
            f"Kapitelende: {_fmt_duration(info.chapter_end_s)}",
            f"Videoframes: {info.video_frame_count if info.video_frame_count is not None else 'unbekannt'}",
            f"Framerate: {_fps_label(info.frame_rate)}{_derived_fps_suffix(info)}",
            f"Framerate-Modus: {info.frame_rate_mode}",
            f"Erwartete Videodauer: {_fmt_duration(info.expected_video_duration_s)}",
            f"Streams: Video={info.video_stream_count}, Audio={info.audio_stream_count}, "
            f"Untertitel={info.subtitle_stream_count}, Attachments={info.attachment_stream_count}",
        ]

    def ffmpeg_supports_setts(self) -> bool:
        if self._setts_supported is not None:
            return self._setts_supported
        try:
            run = self._runtime.run_tool(
                [self._runtime.ffmpeg_path, "-hide_banner", "-bsfs"],
                label="FFmpeg-Bitstreamfilter-Prüfung",
            )
            text = f"{run.stdout}\n{run.stderr}"
            self._setts_supported = run.returncode == 0 and "setts" in text.split()
        except (OSError, ValueError, RuntimeError) as exc:
            self._setts_supported = False
            self._runtime.log(f"⚠️ FFmpeg-setts-Unterstützung konnte nicht geprüft werden: {exc}", "warn")
        return bool(self._setts_supported)

    def _tool_availability_error(self, container_name: str) -> str:
        if container_name == "mp4":
            if not tool_available(self._runtime.mp4box_path):
                return "MP4Box wurde nicht gefunden - MP4-Timestamp-Reparatur nicht möglich."
            return ""
        if not tool_available(self._runtime.ffmpeg_path):
            return "ffmpeg wurde nicht gefunden - Timestamp-Reparatur nicht möglich."
        return ""

    def _log_reference_inventories(self, ffprobe: StreamInventory, mediainfo: StreamInventory) -> None:
        def label(inv: StreamInventory) -> str:
            if not inv.available:
                return f"{inv.source}=nicht verfügbar"
            return f"{inv.source}: V={inv.video}, A={inv.audio}, S={inv.subtitle}"

        self._runtime.log(f"   Stream-Referenz: {label(ffprobe)} | {label(mediainfo)}", "info")


def _fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "unbekannt"
    try:
        return f"{float(seconds):.1f}s"
    except (TypeError, ValueError):
        return "unbekannt"
