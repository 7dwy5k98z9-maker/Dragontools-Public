# -*- coding: utf-8 -*-
from __future__ import annotations


class WorkflowVerificationService:
    """Validiert den Pipeline-Output und fuehrt optionale Laufzeitreparatur aus."""

    def __init__(self, *, output_verifier, duration_repair_service, logger) -> None:
        self._output_verifier = output_verifier
        self._duration_repair_service = duration_repair_service
        self._logger = logger

    def verify(self, ctx) -> None:
        source_has_audio = bool(getattr(ctx.analysis, "audio_streams", []) or [])
        expected_contract = getattr(ctx, "expected_media_contract", None)
        required_output_audio = (
            bool(expected_contract.audio_tracks)
            if expected_contract is not None
            else source_has_audio
        )
        verify_kwargs = {
            "expected_duration_ms": ctx.duration_ms,
            "source_has_audio": required_output_audio,
        }
        if expected_contract is not None:
            verify_kwargs["expected_contract"] = expected_contract
        if bool(getattr(ctx, "pipeline_verified_hdr10plus", False)):
            verify_kwargs["verified_hdr10plus"] = True
        if bool(getattr(ctx, "pipeline_verified_dolby_vision", False)):
            verify_kwargs["verified_dolby_vision"] = True

        result = self._output_verifier.verify(
            ctx.output_path,
            ctx.container,
            **verify_kwargs,
        )
        ctx.verify_result = result
        if not result.ok:
            result = self._try_duration_repair(ctx, result, required_output_audio)
            ctx.verify_result = result
            if result.ok:
                self._log_verify_success(result)
                return
            self._log_verify_failure(result)
            raise RuntimeError(f"Verify fehlgeschlagen: {self._verify_detail(result)}")
        self._log_verify_success(result)

    def _try_duration_repair(self, ctx, result, source_has_audio: bool):
        repair_service = self._duration_repair_service
        if repair_service is None:
            return result
        if not repair_service.can_repair(
            output_path=ctx.output_path,
            container=ctx.container,
            verify_result=result,
        ):
            return result

        outcome = repair_service.repair(
            output_path=ctx.output_path,
            base_dir=ctx.base_dir,
            container=ctx.container,
            expected_duration_ms=ctx.duration_ms,
            source_has_audio=source_has_audio,
            initial_result=result,
            expected_contract=getattr(ctx, "expected_media_contract", None),
            verified_hdr10plus=bool(getattr(ctx, "pipeline_verified_hdr10plus", False)),
            verified_dolby_vision=bool(getattr(ctx, "pipeline_verified_dolby_vision", False)),
        )
        ctx.duration_repair_attempted = bool(getattr(outcome, "attempted", False))
        ctx.duration_after_ffmpeg_s = getattr(result, "duration_s", None)
        ctx.duration_after_remux_s = getattr(outcome, "remux_duration_s", None)
        ctx.duration_after_timestamp_fix_s = getattr(outcome, "timestamp_duration_s", None)
        timestamp_fixed = bool(getattr(outcome, "timestamp_fixed", False))
        remux_fixed = bool(getattr(outcome, "repaired", False)) and not timestamp_fixed
        ctx.duration_repair_method = (
            "timestamp" if timestamp_fixed else ("remux" if remux_fixed else "")
        )
        ctx.duration_repair_reason = str(
            getattr(outcome, "timestamp_repair_reason", "") or ""
        )
        repair_command = (
            getattr(outcome, "timestamp_repair_cmd", None)
            or getattr(outcome, "timestamp_ffmpeg_cmd", None)
        )
        ctx.duration_repair_command = repair_command
        ctx.duration_repair_ffmpeg_cmd = repair_command
        ctx.duration_repair_timing_summary = getattr(outcome, "timing_summary", None)
        archive_path = getattr(outcome, "archived_path", None)
        ctx.duration_repair_archive_path = archive_path
        ctx.keep_failed_output = bool(getattr(outcome, "keep_failed_output", False))
        repaired_result = getattr(outcome, "verify_result", None) or result
        messages = list(getattr(repaired_result, "messages", []) or [])
        outcome_message = str(getattr(outcome, "message", "") or "")
        if outcome_message and outcome_message not in messages:
            messages.append(outcome_message)
        if archive_path:
            ctx.output_path = archive_path
            archive_message = f"Fehlerhafte Ausgabedatei wurde archiviert: {archive_path}"
            if archive_message not in messages:
                messages.append(archive_message)
        repaired_result.messages = messages
        return repaired_result

    @staticmethod
    def _verify_detail(result) -> str:
        messages = [str(msg) for msg in (result.messages or []) if msg]
        return "; ".join(messages) if messages else "Ausgabe nicht plausibel."

    def _log_verify_failure(self, result) -> None:
        for message in [str(msg) for msg in (result.messages or []) if msg]:
            self._logger.error(f"Output-Validierung: {message}")

    def _log_verify_success(self, result) -> None:
        if result.duration_s is not None:
            self._logger.info(
                "Output-Validierung OK: "
                f"Video={result.video_stream_count}, Audio={result.audio_stream_count}, "
                f"Dauer={result.duration_s:.1f}s"
            )
        else:
            self._logger.info("Output-Validierung OK")
