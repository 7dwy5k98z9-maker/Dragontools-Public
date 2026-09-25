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
from .duration_original_timeline_service import OriginalTimelineRepairService
from .duration_repair_runtime import DurationRepairRuntime
from .duration_repair_stream_guard import RepairStreamGuard, StreamInventory
from .duration_repair_validation import source_video_reference_s
from .duration_timestamp_candidate_service import TimestampCandidateService
from .duration_timing_analyzer import MediaTimingAnalyzer, _fps_label
from .duration_timestamp_helpers import (
    allow_one_frame_wrap_cfr_repair,
    log_reference_inventories,
    mkv_video_track_id,
    timestamp_tool_availability_error,
)
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
            mkvmerge_path=runtime.mkvmerge_path,
            run_tool_fn=runtime.run_tool,
            log=runtime.log,
        )
        self._candidate_service = TimestampCandidateService(runtime, timing_analyzer, self._stream_guard)
        self._original_timeline_service = OriginalTimelineRepairService(runtime, timing_analyzer, self._stream_guard)

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
        source_path: str | None = None,
    ) -> TimestampRepairResult:
        if not tool_available(self._runtime.ffprobe_path):
            reason = "ffprobe wurde nicht gefunden - Timestamp-Prüfung nicht möglich."
            self._runtime.log(f"❌ {reason}", "error")
            return TimestampRepairResult(verify_result=reference_result, reason=reason)

        self._runtime.log("ℹ️ [Reparatur 2/2] Timestamp-Prüfung gestartet.", "info")

        source_reference, video_reference_s = _load_source_timing_reference(
            self, source_path, expected_duration_ms, expected_duration_s
        )

        before = self.get_media_timing_info(str(out), expected_duration_s=video_reference_s)
        summary = self.timing_summary(before)
        for line in summary:
            self._runtime.log(f"   {line}", "info")

        problem = detect_timestamp_problem(before, expected_duration_s=video_reference_s)
        original_fallback = None
        vfr_fallback_reason = ""
        if not problem.should_repair:
            original_fallback = _try_original_timeline_fallback(
                service=self._original_timeline_service, problem_reason=problem.reason, before=before,
                source_path=source_path, out=out, base_dir=base_dir, container=container,
                expected_duration_ms=expected_duration_ms, expected_duration_s=video_reference_s,
                source_has_audio=source_has_audio, reference_result=reference_result, timing_summary=summary,
                expected_contract=expected_contract, verified_hdr10plus=verified_hdr10plus,
                verified_dolby_vision=verified_dolby_vision,
            )
            if original_fallback is not None and original_fallback.repaired:
                return original_fallback
            if original_fallback is not None:
                vfr_fallback_reason = original_fallback.reason or ""
            if not allow_one_frame_wrap_cfr_repair(
                before, expected_duration_s=video_reference_s, fallback_reason=vfr_fallback_reason
            ):
                if original_fallback is not None:
                    return original_fallback
                self._runtime.log(f"⚠️ Keine sichere Timestamp-Reparatur: {problem.reason}", "warn")
                return TimestampRepairResult(
                    verify_result=reference_result,
                    reason=f"Keine sichere Timestamp-Reparatur: {problem.reason}",
                    timing_summary=summary,
                )
            self._runtime.log(
                "⚠️ VFR-Originaltimeline weicht nur um 1 Frame ab und die Datei zeigt einen extremen "
                "Timestamp-Wrap. Starte sicheren CFR-Neuaufbau mit der bekannten Referenzframerate.",
                "warn",
            )

        self._runtime.log("⚠️ Extreme Abweichung im Videostream erkannt.", "warn")
        self._runtime.log("ℹ️ Starte verlustfreie Timestamp-Reparatur.", "info")
        if before.frame_rate is not None:
            self._runtime.log(f"   Rekonstruktionsrate: {_fps_label(before.frame_rate)} fps", "info")

        container_name = str(container or "").strip().lower().lstrip(".")
        availability_error = timestamp_tool_availability_error(self._runtime, container_name)
        if availability_error:
            self._runtime.log(f"❌ {availability_error}", "error")
            return TimestampRepairResult(
                verify_result=reference_result,
                reason=availability_error,
                timing_summary=summary,
            )

        before_ffprobe, before_mediainfo, before_mkvmerge = self._stream_guard.inspect_all(str(out))
        log_reference_inventories(self._runtime, before_ffprobe, before_mediainfo, before_mkvmerge)
        repaired = self.repair_video_timestamps(
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
            before_mkvmerge=before_mkvmerge,
            source_reference=source_reference,
        )
        if (
            not repaired.repaired
            and original_fallback is not None
            and repaired.reason == "Kein geeignetes Werkzeug für die Timestamp-Reparatur verfügbar."
        ):
            return original_fallback
        return repaired

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
        before_mkvmerge: StreamInventory | None = None,
        source_reference: MediaTimingInfo | None = None,
    ) -> TimestampRepairResult:
        if before.frame_rate is None:
            return TimestampRepairResult(reason="Framerate fehlt.", timing_summary=timing_summary)
        if before_ffprobe is None or before_mediainfo is None or before_mkvmerge is None:
            inspected = self._stream_guard.inspect_all(str(out))
            before_ffprobe = before_ffprobe or inspected[0]
            before_mediainfo = before_mediainfo or inspected[1]
            before_mkvmerge = before_mkvmerge or inspected[2]

        container_name = str(container or "").strip().lower().lstrip(".")
        attempts: list[tuple[Path, list[str], str, str]] = []

        if container_name == "mp4":
            tmp = out.with_name(f"{out.stem}.timestamp_fix_{uuid4().hex}{out.suffix}")
            command = self.build_timestamp_repair_command(out, tmp, before.frame_rate, container=container)
            attempts.append((tmp, command, "MP4Box-Timestamp-Reparatur", "MP4Box CFR-Neuaufbau"))
        else:
            if tool_available(self._runtime.mkvmerge_path):
                try:
                    track_id = mkv_video_track_id(self._runtime, out)
                    tmp = out.with_name(f"{out.stem}.timestamp_mkvmerge_{uuid4().hex}{out.suffix}")
                    command = build_timestamp_repair_command(
                        out, tmp, before.frame_rate, container=container,
                        mp4box_path=self._runtime.mp4box_path, ffmpeg_path=self._runtime.ffmpeg_path,
                        mkvmerge_path=self._runtime.mkvmerge_path, mkv_video_track_id=track_id,
                    )
                    attempts.append((tmp, command, "MKVToolNix-default-duration-Timestamp-Reparatur", "MKVToolNix --default-duration"))
                except Exception as exc:
                    self._runtime.log(f"⚠️ MKVToolNix-Videotrack-ID konnte nicht bestimmt werden: {exc}", "warn")

            if tool_available(self._runtime.ffmpeg_path) and self.ffmpeg_supports_setts():
                tmp = out.with_name(f"{out.stem}.timestamp_setts_{uuid4().hex}{out.suffix}")
                command = build_timestamp_repair_command(
                    out, tmp, before.frame_rate, container=container,
                    mp4box_path=self._runtime.mp4box_path, ffmpeg_path=self._runtime.ffmpeg_path,
                )
                attempts.append((tmp, command, "FFmpeg-setts-Timestamp-Reparatur", "FFmpeg setts"))

            if tool_available(self._runtime.ffmpeg_path):
                tmp = out.with_name(f"{out.stem}.timestamp_genpts_{uuid4().hex}{out.suffix}")
                attempts.append((
                    tmp,
                    build_genpts_repair_command(out, tmp, ffmpeg_path=self._runtime.ffmpeg_path),
                    "FFmpeg-+genpts+igndts-Timestamp-Reparatur",
                    "FFmpeg +genpts+igndts",
                ))

        if not attempts:
            return TimestampRepairResult(
                attempted=False,
                reason="Kein geeignetes Werkzeug für die Timestamp-Reparatur verfügbar.",
                timing_summary=timing_summary,
            )

        previous_reasons: list[str] = []
        last_result: TimestampRepairResult | None = None
        for attempt_no, (tmp, command, label, method) in enumerate(attempts, start=1):
            if method == "MKVToolNix --default-duration":
                self._runtime.log(
                    f"   MKVToolNix default-duration: {_fps_label(before.frame_rate)} fps "
                    f"(verlustfreier Remux, Track-ID aus mkvmerge -J)",
                    "info",
                )
            elif method == "FFmpeg setts":
                self._runtime.log("   FFmpeg setts: " + command_arg_after(command, "-bsf:v:0"), "info")
            elif method == "MP4Box CFR-Neuaufbau":
                self._runtime.log(f"   MP4Box CFR-Neuaufbau: {_fps_label(before.frame_rate)} fps", "info")
            elif attempt_no > 1:
                self._runtime.log("ℹ️ Starte verlustfreien FFmpeg-+genpts/+igndts-Fallback.", "info")

            try:
                result = self._attempt_candidate(
                    out=out, tmp=tmp, base_dir=base_dir, command=command, label=label, method=method,
                    container=container, before=before, before_ffprobe=before_ffprobe,
                    before_mediainfo=before_mediainfo, before_mkvmerge=before_mkvmerge,
                    expected_duration_ms=expected_duration_ms, source_has_audio=source_has_audio,
                    timing_summary=timing_summary, expected_contract=expected_contract,
                    verified_hdr10plus=verified_hdr10plus, verified_dolby_vision=verified_dolby_vision,
                    source_reference=source_reference,
                )
            except Exception as exc:
                self._runtime.safe_unlink(tmp)
                result = TimestampRepairResult(
                    attempted=True, reason=f"{label} fehlgeschlagen: {exc}", command=command,
                    timing_summary=timing_summary, retry_recommended=True, method=method,
                )
            if result.repaired:
                return result
            last_result = result
            if result.reason:
                previous_reasons.append(f"{method}: {result.reason}")
            if attempt_no < len(attempts):
                self._runtime.log(
                    f"ℹ️ Reparaturversuch {attempt_no}/{len(attempts)} wurde nicht akzeptiert; "
                    "nächster lossless Fallback startet.",
                    "info",
                )

        if last_result is None:
            return TimestampRepairResult(
                attempted=False,
                reason="Kein Timestamp-Reparaturversuch wurde ausgeführt.",
                timing_summary=timing_summary,
            )
        if previous_reasons:
            last_result.reason = " | ".join(previous_reasons)
        return last_result

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
        return _timing_summary(info)

    def ffmpeg_supports_setts(self) -> bool:
        return _ffmpeg_supports_setts(self)




def _load_source_timing_reference(
    service: TimestampRepairService,
    source_path: str | None,
    expected_duration_ms: int | None,
    expected_duration_s: float | None,
) -> tuple[MediaTimingInfo | None, float | None]:
    """Measure the original source separately from the damaged encoded output."""
    source_reference = None
    if source_path:
        try:
            source_reference = service.get_media_timing_info(str(source_path))
            service._runtime.log(
                "   Original-Referenz: "
                f"Container={_fmt_duration(source_reference.container_duration_s)} | "
                f"Video={_fmt_duration(source_reference.video_duration_s)} | "
                f"Frame/FPS={_fmt_duration(source_reference.expected_video_duration_s)} | "
                f"Frames={source_reference.video_frame_count if source_reference.video_frame_count is not None else 'unbekannt'}",
                "info",
            )
        except Exception as exc:
            service._runtime.log(
                f"⚠️ Original-Timingreferenz konnte nicht vollständig ermittelt werden: {exc}",
                "warn",
            )
    video_reference_s = source_video_reference_s(
        source_reference, expected_duration_ms=expected_duration_ms
    ) or expected_duration_s
    return source_reference, video_reference_s


def _timing_summary(info: MediaTimingInfo) -> list[str]:
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


def _ffmpeg_supports_setts(service: TimestampRepairService) -> bool:
    if service._setts_supported is not None:
        return service._setts_supported
    try:
        run = service._runtime.run_tool(
            [service._runtime.ffmpeg_path, "-hide_banner", "-bsfs"],
            label="FFmpeg-Bitstreamfilter-Prüfung",
        )
        value = f"{run.stdout}\n{run.stderr}"
        service._setts_supported = run.returncode == 0 and "setts" in value.split()
    except (OSError, ValueError, RuntimeError) as exc:
        service._setts_supported = False
        service._runtime.log(
            f"⚠️ FFmpeg-setts-Unterstützung konnte nicht geprüft werden: {exc}", "warn"
        )
    return bool(service._setts_supported)

def _try_original_timeline_fallback(
    *, service: OriginalTimelineRepairService, problem_reason: str, before: MediaTimingInfo,
    source_path: str | None, out: Path, base_dir: Path | None, container: str,
    expected_duration_ms: int | None, expected_duration_s: float | None, source_has_audio: bool,
    reference_result: WorkflowVerifyResult, timing_summary: list[str], expected_contract,
    verified_hdr10plus: bool, verified_dolby_vision: bool,
) -> TimestampRepairResult | None:
    if (before.frame_rate_mode or "").upper() != "VFR" or not source_path:
        return None
    result = service.try_repair(
        source=Path(source_path), out=out, base_dir=base_dir, container=container,
        expected_duration_ms=expected_duration_ms, expected_duration_s=expected_duration_s,
        source_has_audio=source_has_audio, reference_result=reference_result, before=before,
        timing_summary=timing_summary, expected_contract=expected_contract,
        verified_hdr10plus=verified_hdr10plus, verified_dolby_vision=verified_dolby_vision,
    )
    if result.repaired:
        return result
    if result.reason:
        result.reason = (
            f"Keine sichere CFR-Timestamp-Reparatur: {problem_reason} "
            f"Original-Timeline-Fallback: {result.reason}"
        )
        return result
    return None



def _fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "unbekannt"
    try:
        return f"{float(seconds):.1f}s"
    except (TypeError, ValueError):
        return "unbekannt"
