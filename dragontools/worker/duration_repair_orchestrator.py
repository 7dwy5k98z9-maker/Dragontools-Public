# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..core.process_runner import tool_available
from .duration_repair_archive import DurationRepairArchive, format_duration
from .duration_repair_models import DurationRepairOutcome, TimestampRepairResult
from .duration_repair_policy import mark_duration_repair_failed
from .duration_remux_service import DurationRemuxService
from .duration_timestamp_service import TimestampRepairService
from .workflow_engine import WorkflowVerifyResult


@dataclass(slots=True)
class _RemuxStage:
    verify_result: WorkflowVerifyResult
    duration_s: float | None = None
    repaired: bool = False
    message: str = ""


class DurationRepairOrchestrator:
    """Coordinates remux, timestamp repair and fail-closed archival."""

    def __init__(
        self,
        *,
        remux_service: DurationRemuxService,
        timestamp_service: TimestampRepairService,
        archive: DurationRepairArchive,
        log,
    ) -> None:
        self._remux_service = remux_service
        self._timestamp_service = timestamp_service
        self._archive = archive
        self._log = log

    def repair(
        self,
        *,
        output_path: str,
        base_dir: Path | None,
        container: str,
        expected_duration_ms: int | None,
        source_has_audio: bool,
        initial_result: WorkflowVerifyResult,
        expected_contract=None,
        verified_hdr10plus: bool = False,
        verified_dolby_vision: bool = False,
        normal_remux_enabled: bool = True,
        timestamp_repair_enabled: bool = True,
    ) -> DurationRepairOutcome:
        out = Path(output_path)
        expected_s = expected_duration_ms / 1000.0 if expected_duration_ms else None
        self._log_start(container, expected_s, initial_result.duration_s)
        remux = self._run_remux(
            out=out,
            container=container,
            expected_duration_ms=expected_duration_ms,
            source_has_audio=source_has_audio,
            initial_result=initial_result,
            expected_contract=expected_contract,
            verified_hdr10plus=verified_hdr10plus,
            verified_dolby_vision=verified_dolby_vision,
            enabled=normal_remux_enabled,
        )
        if remux.repaired:
            return DurationRepairOutcome(
                attempted=True,
                repaired=True,
                verify_result=remux.verify_result,
                remux_duration_s=remux.duration_s,
                message="Laufzeit durch automatischen Remux korrigiert.",
            )

        timestamp = self._run_timestamp(
            out=out,
            container=container,
            base_dir=base_dir,
            expected_duration_ms=expected_duration_ms,
            expected_duration_s=expected_s,
            source_has_audio=source_has_audio,
            reference_result=remux.verify_result,
            expected_contract=expected_contract,
            verified_hdr10plus=verified_hdr10plus,
            verified_dolby_vision=verified_dolby_vision,
            enabled=timestamp_repair_enabled,
        )
        if timestamp.repaired:
            return self._timestamp_success(remux.duration_s, timestamp)
        return self._failed_outcome(
            out=out,
            base_dir=base_dir,
            initial_result=initial_result,
            expected_s=expected_s,
            ffmpeg_s=initial_result.duration_s,
            remux=remux,
            timestamp=timestamp,
        )

    def _run_remux(self, **kwargs) -> _RemuxStage:
        initial_result = kwargs["initial_result"]
        container = kwargs["container"]
        tool_path, tool_label = self._remux_service.normal_remux_tool(container)
        enabled = bool(kwargs.pop("enabled"))
        if not enabled:
            message = "Normaler Container-Remux ist in den Einstellungen deaktiviert."
            self._log(f"ℹ️ {message}", "info")
            return _RemuxStage(initial_result, message=message)
        if not tool_path or not tool_available(tool_path):
            message = f"{tool_label} wurde nicht gefunden - normaler Remux wird übersprungen."
            self._log(f"⚠️ {message}", "warn")
            return _RemuxStage(initial_result, message=message)
        verify_result, duration_s, repaired, message = self._remux_service.attempt(**kwargs)
        return _RemuxStage(verify_result, duration_s, repaired, message)

    def _run_timestamp(self, **kwargs) -> TimestampRepairResult:
        enabled = bool(kwargs.pop("enabled"))
        if enabled:
            return self._timestamp_service.try_repair(**kwargs)
        reason = "Timestamp-Reparatur ist in den Einstellungen deaktiviert."
        self._log(f"ℹ️ {reason}", "info")
        return TimestampRepairResult(verify_result=kwargs["reference_result"], reason=reason)

    @staticmethod
    def _timestamp_success(remux_duration_s: float | None, result: TimestampRepairResult) -> DurationRepairOutcome:
        return DurationRepairOutcome(
            attempted=True,
            repaired=True,
            verify_result=result.verify_result,
            remux_duration_s=remux_duration_s,
            timestamp_fix_attempted=result.attempted,
            timestamp_fixed=True,
            timestamp_duration_s=result.duration_s,
            timestamp_repair_reason=result.reason,
            timestamp_repair_cmd=result.command,
            timestamp_ffmpeg_cmd=result.command,
            timing_summary=result.timing_summary,
            message="Laufzeit durch automatische Timestamp-Reparatur korrigiert.",
        )

    def _failed_outcome(
        self,
        *,
        out: Path,
        base_dir: Path | None,
        initial_result: WorkflowVerifyResult,
        expected_s: float | None,
        ffmpeg_s: float | None,
        remux: _RemuxStage,
        timestamp: TimestampRepairResult,
    ) -> DurationRepairOutcome:
        final_result = timestamp.verify_result or remux.verify_result or initial_result
        messages = list(getattr(final_result, "messages", []) or [])
        for message in (remux.message, timestamp.reason):
            if message and message not in messages:
                messages.append(message)
        if remux.duration_s is not None:
            messages.append("Laufzeit blieb auch nach automatischem Container-Remux unplausibel.")

        self._log("❌ Laufzeit bleibt nach automatischer Reparatur unplausibel.", "error")
        self._log(
            f"   Quelle: {format_duration(expected_s)} | nach FFmpeg: {format_duration(ffmpeg_s)} | "
            f"nach Remux: {format_duration(remux.duration_s)} | nach Timestamp-Fix: "
            f"{format_duration(timestamp.duration_s)}",
            "error",
        )
        archived = self._archive.archive(out, base_dir)
        if archived:
            messages.append(f"Fehlerhafte Ausgabedatei wurde archiviert: {archived}")
        mark_duration_repair_failed(final_result, messages)
        return DurationRepairOutcome(
            attempted=True,
            repaired=False,
            verify_result=final_result,
            archived_path=archived,
            remux_duration_s=remux.duration_s,
            timestamp_fix_attempted=timestamp.attempted,
            timestamp_fixed=False,
            timestamp_duration_s=timestamp.duration_s,
            timestamp_repair_reason=timestamp.reason,
            timestamp_repair_cmd=timestamp.command,
            timestamp_ffmpeg_cmd=timestamp.command,
            timing_summary=timestamp.timing_summary,
            keep_failed_output=True,
            message="Laufzeit blieb auch nach automatischer Reparatur unplausibel.",
        )

    def _log_start(self, container: str, expected_s: float | None, ffmpeg_s: float | None) -> None:
        self._log(
            f"⚠️ Ausgabedauer unplausibel - automatische {str(container).upper()}-Reparatur startet.",
            "warn",
        )
        self._log(
            f"   Quelle: {format_duration(expected_s)} | nach FFmpeg: {format_duration(ffmpeg_s)}",
            "warn",
        )
