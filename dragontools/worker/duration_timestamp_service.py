# -*- coding: utf-8 -*-
from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from uuid import uuid4

from ..core.process_runner import tool_available
from .duration_repair_commands import build_timestamp_repair_command, command_arg_after
from .duration_repair_models import MediaTimingInfo, TimestampRepairResult, detect_timestamp_problem
from .duration_repair_runtime import DurationRepairRuntime
from .duration_repair_validation import validate_timestamp_repair
from .duration_timing_analyzer import MediaTimingAnalyzer, _fps_label
from .tool_runner import log_tool_failure
from .workflow_engine import WorkflowVerifyResult


class TimestampRepairService:
    """Stage 2: diagnose and rebuild damaged video timestamps without re-encoding."""

    def __init__(self, runtime: DurationRepairRuntime, timing_analyzer: MediaTimingAnalyzer) -> None:
        self._runtime = runtime
        self._timing_analyzer = timing_analyzer
        self._setts_supported: bool | None = None

    def try_repair(
        self,
        *,
        out: Path,
        container: str,
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
            self._runtime.log(
                f"   Videotimeline wird mit {_fps_label(before.frame_rate)} fps rekonstruiert.",
                "info",
            )

        container_name = str(container or "").strip().lower().lstrip(".")
        if container_name == "mp4":
            if not tool_available(self._runtime.mp4box_path):
                reason = "MP4Box wurde nicht gefunden - MP4-Timestamp-Reparatur nicht möglich."
                self._runtime.log(f"❌ {reason}", "error")
                return TimestampRepairResult(verify_result=reference_result, reason=reason, timing_summary=summary)
        else:
            if not tool_available(self._runtime.ffmpeg_path):
                reason = "ffmpeg wurde nicht gefunden - Timestamp-Reparatur nicht möglich."
                self._runtime.log(f"❌ {reason}", "error")
                return TimestampRepairResult(verify_result=reference_result, reason=reason, timing_summary=summary)
            if not self.ffmpeg_supports_setts():
                reason = "Die gefundene FFmpeg-Version unterstützt den setts-Bitstreamfilter nicht."
                self._runtime.log(f"❌ {reason}", "error")
                return TimestampRepairResult(verify_result=reference_result, reason=reason, timing_summary=summary)

        return self.repair_video_timestamps(
            out=out,
            container=container,
            expected_duration_ms=expected_duration_ms,
            source_has_audio=source_has_audio,
            before=before,
            timing_summary=summary,
            expected_contract=expected_contract,
            verified_hdr10plus=verified_hdr10plus,
            verified_dolby_vision=verified_dolby_vision,
        )

    def get_media_timing_info(self, path: str, *, expected_duration_s: float | None = None) -> MediaTimingInfo:
        return self._timing_analyzer.get_media_timing_info(path, expected_duration_s=expected_duration_s)

    def repair_video_timestamps(
        self,
        *,
        out: Path,
        container: str,
        expected_duration_ms: int | None,
        source_has_audio: bool,
        before: MediaTimingInfo,
        timing_summary: list[str],
        expected_contract=None,
        verified_hdr10plus: bool = False,
        verified_dolby_vision: bool = False,
    ) -> TimestampRepairResult:
        if before.frame_rate is None:
            return TimestampRepairResult(reason="Framerate fehlt.", timing_summary=timing_summary)

        tmp = out.with_name(f"{out.stem}.timestamp_fix_{uuid4().hex}{out.suffix}")
        command = self.build_timestamp_repair_command(out, tmp, before.frame_rate, container=container)
        container_name = str(container or "").strip().lower().lstrip(".")
        if container_name == "mp4":
            self._runtime.log(f"   MP4Box CFR-Neuaufbau: {_fps_label(before.frame_rate)} fps", "info")
        else:
            self._runtime.log("   FFmpeg setts: " + command_arg_after(command, "-bsf:v:0"), "info")
        try:
            label = "MP4Box-Timestamp-Reparatur" if container_name == "mp4" else "FFmpeg-Timestamp-Reparatur"
            run = self._runtime.run_tool(command, label=label)
            if run.returncode != 0:
                tool_name = "MP4Box" if container_name == "mp4" else "ffmpeg"
                stderr = (run.stderr or run.stdout or f"{tool_name} fehlgeschlagen.").strip()
                log_tool_failure(run, label=label, log=self._runtime.log, tool_name=tool_name)
                if stderr:
                    self._runtime.log(
                        f"❌ {tool_name}-Timestamp-Reparatur fehlgeschlagen: {stderr.splitlines()[-1]}",
                        "error",
                    )
                self._runtime.safe_unlink(tmp)
                return TimestampRepairResult(
                    attempted=True,
                    verify_result=None,
                    reason=(
                        "MP4Box-Timestamp-Reparatur fehlgeschlagen."
                        if container_name == "mp4"
                        else "FFmpeg-Timestamp-Reparatur fehlgeschlagen."
                    ),
                    command=command,
                    timing_summary=timing_summary,
                )
            if not tmp.exists() or tmp.stat().st_size < max(1024, int(out.stat().st_size * 0.25)):
                self._runtime.safe_unlink(tmp)
                return TimestampRepairResult(
                    attempted=True,
                    reason="Timestamp-Reparatur erzeugte keine plausible Ausgabedatei.",
                    command=command,
                    timing_summary=timing_summary,
                )

            repaired_info = self.get_media_timing_info(str(tmp))
            verify_kwargs = {
                "expected_duration_ms": expected_duration_ms,
                "source_has_audio": source_has_audio,
            }
            if expected_contract is not None:
                verify_kwargs["expected_contract"] = expected_contract
            if verified_hdr10plus:
                verify_kwargs["verified_hdr10plus"] = True
            if verified_dolby_vision:
                verify_kwargs["verified_dolby_vision"] = True
            verify_result = self._runtime.output_verifier.verify(str(tmp), container, **verify_kwargs)
            ok, validation_messages = validate_timestamp_repair(
                before=before,
                repaired=repaired_info,
                verify_result=verify_result,
                expected_duration_ms=expected_duration_ms,
                source_has_audio=source_has_audio,
            )
            if not ok:
                for message in validation_messages:
                    self._runtime.log(f"❌ Timestamp-Reparatur verworfen: {message}", "error")
                messages = list(verify_result.messages or [])
                messages.extend(validation_messages)
                verify_result.messages = messages
                duration_s = repaired_info.container_duration_s or verify_result.duration_s
                self._runtime.safe_unlink(tmp)
                return TimestampRepairResult(
                    attempted=True,
                    verify_result=verify_result,
                    duration_s=duration_s,
                    reason="Timestamp-Reparatur wurde nach Validierung verworfen.",
                    command=command,
                    timing_summary=timing_summary,
                )

            self._runtime.replace_file(tmp, out)
            duration_s = repaired_info.container_duration_s or verify_result.duration_s
            self._runtime.log("✅ Timestamp-Reparatur erfolgreich.", "info")
            self._runtime.log(
                f"   Reparierte Videodauer: {_fmt_duration(repaired_info.video_duration_s)} | "
                f"Audiodauer: {_fmt_duration(repaired_info.audio_duration_s)} | "
                f"Container: {_fmt_duration(repaired_info.container_duration_s)}",
                "info",
            )
            return TimestampRepairResult(
                attempted=True,
                repaired=True,
                verify_result=verify_result,
                duration_s=duration_s,
                reason="Timestamp-Reparatur erfolgreich.",
                command=command,
                timing_summary=timing_summary,
            )
        except Exception as exc:
            self._runtime.safe_unlink(tmp)
            self._runtime.log(f"❌ Timestamp-Reparatur fehlgeschlagen: {exc}", "error")
            return TimestampRepairResult(
                attempted=True,
                reason=f"Timestamp-Reparatur fehlgeschlagen: {exc}",
                command=command,
                timing_summary=timing_summary,
            )

    def validate_timestamp_repair(
        self,
        *,
        before: MediaTimingInfo,
        repaired: MediaTimingInfo,
        verify_result: WorkflowVerifyResult,
        expected_duration_ms: int | None,
        source_has_audio: bool,
    ) -> tuple[bool, list[str]]:
        return validate_timestamp_repair(
            before=before,
            repaired=repaired,
            verify_result=verify_result,
            expected_duration_ms=expected_duration_ms,
            source_has_audio=source_has_audio,
        )

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


def _fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "unbekannt"
    try:
        return f"{float(seconds):.1f}s"
    except (TypeError, ValueError):
        return "unbekannt"
