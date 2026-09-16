# -*- coding: utf-8 -*-
from __future__ import annotations

from .output_verification_archive import preserve_failed_verification_output
from .workflow_duration_repair import try_duration_repair
from .workflow_geometry_validation import apply_geometry_policy


class WorkflowVerificationService:
    """Validiert Pipeline-Output; Geometrie und Repair liegen in Fachmodulen."""

    def __init__(self, *, output_verifier, duration_repair_service, logger) -> None:
        self._output_verifier = output_verifier
        self._duration_repair_service = duration_repair_service
        self._logger = logger

    def verify(self, ctx) -> None:
        expected = getattr(ctx, "expected_media_contract", None)
        source_has_audio = bool(getattr(ctx.analysis, "audio_streams", []) or [])
        required_audio = bool(expected.audio_tracks) if expected is not None else source_has_audio
        kwargs = {"expected_duration_ms": ctx.duration_ms, "source_has_audio": required_audio}
        if expected is not None:
            kwargs["expected_contract"] = expected
        if bool(getattr(ctx, "pipeline_verified_hdr10plus", False)):
            kwargs["verified_hdr10plus"] = True
        if bool(getattr(ctx, "pipeline_verified_dolby_vision", False)):
            kwargs["verified_dolby_vision"] = True

        result = self._output_verifier.verify(ctx.output_path, ctx.container, **kwargs)
        ctx.verify_result = result
        if apply_geometry_policy(ctx, result):
            self._log_warnings(result)
            return

        if not result.ok:
            result = try_duration_repair(ctx, result, required_audio, self._duration_repair_service)
            ctx.verify_result = result
            if result.ok:
                self._log_warnings(result)
                self._log_success(result)
                return
            preserve_failed_verification_output(ctx, result, logger=self._logger)
            self._log_failure(result)
            raise RuntimeError(f"Verify fehlgeschlagen: {self._detail(result)}")

        self._log_warnings(result)
        self._log_success(result)

    @staticmethod
    def _detail(result) -> str:
        messages = [str(msg) for msg in (result.messages or []) if msg]
        return "; ".join(messages) if messages else "Ausgabe nicht plausibel."

    def _log_failure(self, result) -> None:
        for message in [str(msg) for msg in (result.messages or []) if msg]:
            self._logger.error(f"Output-Validierung: {message}")

    def _log_warnings(self, result) -> None:
        for message in [str(msg) for msg in (getattr(result, "warnings", None) or []) if msg]:
            self._logger.warn(f"Output-Validierung: {message}")

    def _log_success(self, result) -> None:
        if result.duration_s is not None:
            self._logger.info(
                "Output-Validierung OK: "
                f"Video={result.video_stream_count}, Audio={result.audio_stream_count}, "
                f"Dauer={result.duration_s:.1f}s"
            )
        else:
            self._logger.info("Output-Validierung OK")
