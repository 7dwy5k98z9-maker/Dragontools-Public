# -*- coding: utf-8 -*-
"""Compatibility facade and orchestrator for Dolby-Vision processing."""
from __future__ import annotations

from pathlib import Path

from ..core.models import TargetCodec
from .dv_pipeline_context import DVRunRequest
from .dv_pipeline_stages import DVPipelineStages
from .dv_pipeline_stage_factory import build_pipeline_stages
from .dv_pipeline_compat import DVPipelineDiagnosticCompatibilityMixin
from .dv_runtime_models import DVEncoderConfig, DVTempState
from .tool_runner import run_tool
from .dv_processing_components import DVProcessingComponents, build_dv_processing_components
from .dv_pipeline_runtime import (
    DVFileValidator,
    DVPipelineDiagnostics,
    DVPipelineRunExecutor,
    DVPreflightService,
)


class DVProcessingPipeline(DVPipelineDiagnosticCompatibilityMixin):
    def __init__(
        self,
        *,
        tools,
        encoder_config: DVEncoderConfig,
        progress_runner,
        subtitle_rules: dict,
        temp_state: DVTempState,
        log,
        verbose_logger=None,
        worker=None,
        components: DVProcessingComponents | None = None,
    ) -> None:
        self._tools = tools
        self._verbose_logger = verbose_logger
        self._encoder_config = encoder_config
        self._progress_runner = progress_runner
        self._subtitle_rules = subtitle_rules
        self._temp_state = temp_state
        self._log_fn = log
        self._worker = worker
        self._diagnostics = DVPipelineDiagnostics()
        self._file_validator = DVFileValidator(
            temp_state=self._temp_state,
            log=self._log,
            verbose_log=self._vlog,
        )

        # Production composition is performed in converter_runtime_builder and
        # injected here.  The fallback remains for tests/legacy callers.
        graph = components or build_dv_processing_components(
            tools=self._tools,
            subtitle_rules=self._subtitle_rules,
            log=self._log,
            verbose_logger=self._verbose_logger,
            worker=self._worker,
        )
        self._audio_mux_service = graph.audio_mux_service
        self._mp4box_muxer = graph.mp4box_muxer
        self._mkv_muxer = graph.mkv_muxer
        self._rpu_service = graph.rpu_service
        self._hdr10plus_service = graph.hdr10plus_service
        self._level5_editor = graph.level5_editor
        self._subtitle_service = graph.subtitle_service
        self._subtitle_mux_service = graph.subtitle_mux_service
        self._failure_recovery = graph.failure_recovery

    def _log(self, message: str, level: str = "info") -> None:
        self._log_fn(message, level)

    def _vlog(self, message: str) -> None:
        if self._verbose_logger is None:
            return
        try:
            self._verbose_logger.write(message)
        except (OSError, RuntimeError, ValueError, AttributeError):
            # Verbose logging is optional and must never break conversion.
            return

    def _clear_burn_sub_tmp(self) -> None:
        self._temp_state.burn_sub_tmp = None

    def _libplacebo_available(self) -> bool:
        try:
            result = run_tool(
                [self._tools.ffmpeg, "-filters"],
                label="ffmpeg libplacebo probe",
                timeout_s=15,
                worker=self._worker,
            )
        except (OSError, ValueError, RuntimeError):
            return False
        return bool(
            result.returncode == 0
            and not result.timed_out
            and not result.aborted
            and "libplacebo" in result.combined_output.lower()
        )

    def _assert_nonempty_file(self, path: Path, label: str) -> bool:
        return self._file_validator.assert_nonempty(path, label)

    def _build_stages(self) -> DVPipelineStages:
        return build_pipeline_stages(
            tools=self._tools,
            encoder_config=self._encoder_config,
            progress_runner=self._progress_runner,
            temp_state=self._temp_state,
            audio_mux_service=self._audio_mux_service,
            mp4box_muxer=self._mp4box_muxer,
            mkv_muxer=self._mkv_muxer,
            rpu_service=self._rpu_service,
            hdr10plus_service=self._hdr10plus_service,
            level5_editor=self._level5_editor,
            subtitle_service=self._subtitle_service,
            subtitle_mux_service=self._subtitle_mux_service,
            subtitle_rules=self._subtitle_rules,
            failure_recovery=self._failure_recovery,
            log=self._log,
            verbose_log=self._vlog,
            assert_nonempty_file=self._assert_nonempty_file,
            clear_burn_sub_tmp=self._clear_burn_sub_tmp,
            crop_decision=getattr(self._worker, "request_dv_crop_decision", None),
        )

    def _reset_run_diagnostics(self) -> None:
        self._diagnostics.reset(self._temp_state)

    def _fail_preflight(self, reason: str, *, stage: str = "DV-Preflight") -> bool:
        return self._diagnostics.fail_preflight(self._temp_state, reason, stage=stage)

    def _handle_run_exception(self, input_path: str, exc: Exception) -> bool:
        return self._diagnostics.record_unhandled_exception(
            input_path=input_path,
            exc=exc,
            temp_state=self._temp_state,
            log=self._log,
        )

    def configure_encoder(self, encoder_config: DVEncoderConfig) -> None:
        self._encoder_config = encoder_config

    def _make_request(
        self,
        *,
        input_path: str,
        output_path: str,
        mi,
        vf_args: list,
        audio_args: list,
        audio_input_args: list | None,
        sn: list,
        crop: str | None,
        ov: dict | None,
        preserve_hdrplus: bool,
        container: str,
    ) -> DVRunRequest:
        return DVRunRequest.create(
            input_path=input_path,
            output_path=output_path,
            media_info=mi,
            vf_args=vf_args,
            audio_args=audio_args,
            audio_input_args=audio_input_args,
            sn=sn,
            crop=crop,
            override=ov,
            preserve_hdrplus=preserve_hdrplus,
            container=container,
        )

    def _preflight(self, request: DVRunRequest) -> bool:
        ok, reason, stage = DVPreflightService(
            tools=self._tools,
            log=self._log,
            verbose_log=self._vlog,
            libplacebo_available=self._libplacebo_available,
        ).validate(encoder_config=self._encoder_config, request=request)
        if ok:
            return True
        return self._fail_preflight(reason, stage=stage)

    def _execute_request(self, request: DVRunRequest) -> bool:
        result, state = DVPipelineRunExecutor(
            temp_state=self._temp_state,
            worker=self._worker,
            log=self._log,
            verbose_log=self._vlog,
            stages_factory=self._build_stages,
        ).execute(request)
        return self._diagnostics.apply_result(result, state, self._temp_state)

    def run(
        self,
        input_path: str,
        output_path: str,
        mi,
        vf_args: list,
        audio_args: list,
        audio_input_args: list | None,
        sn: list,
        crop: str | None,
        ov: dict | None = None,
        preserve_hdrplus: bool = False,
        container: str = "mp4",
    ) -> bool:
        """Normalize request, perform preflight and delegate DV execution."""
        try:
            self._reset_run_diagnostics()
            self._vlog("[TRACE][DV] entered dv_processing_pipeline")
            request = self._make_request(
                input_path=input_path,
                output_path=output_path,
                mi=mi,
                vf_args=vf_args,
                audio_args=audio_args,
                audio_input_args=audio_input_args,
                sn=sn,
                crop=crop,
                ov=ov,
                preserve_hdrplus=preserve_hdrplus,
                container=container,
            )
            if not self._preflight(request):
                return False
            return self._execute_request(request)
        except Exception as exc:
            # Pipeline boundary: record a complete failure diagnostic and never
            # let a worker exception escape without state for the error report.
            return self._handle_run_exception(input_path, exc)


__all__ = ["DVProcessingPipeline"]
