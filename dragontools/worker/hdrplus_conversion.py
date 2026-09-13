# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Callable

from .dv_runtime_models import DVTempState
from .hdrplus_helper_compat import HDRPlusCompatibilityMixin
from .hdrplus_helper_services import build_hdrplus_helper_services
from .hdrplus_pipeline_coordinator import HDRPlusPipelineHooks
from .hdrplus_runtime_models import HDRPlusEncoderConfig, HDRPlusExecutionContext
from .tool_runner import log_tool_failure, run_tool
from .workflow_models import PipelineExecutionRequest, PipelineExecutionResult


class HDRPlusConversionHelper(HDRPlusCompatibilityMixin):
    """Stabile Fassade fuer den HDR10+-Spezialpfad.

    Langlebige Services werden zentral verdrahtet; Jobzustand wird pro Aufruf als
    ``HDRPlusExecutionContext`` an den Pipeline-Coordinator übergeben.
    """

    def __init__(
        self,
        *,
        tools,
        log: Callable[[str, str], None],
        codec: str,
        crf: int | str,
        preset: str,
        encoder_options: dict,
        progress_runner,
        temp_state: DVTempState,
        subtitle_rules: dict | None = None,
    ) -> None:
        self._tools = tools
        self._log_fn = log
        default_encoder = HDRPlusEncoderConfig.create(
            codec=codec,
            crf=crf,
            preset=preset,
            encoder_options=encoder_options,
        )
        self._codec = default_encoder.codec
        self._crf = crf
        self._preset = preset
        self._encoder_options = dict(encoder_options or {})
        self._progress = progress_runner
        self._temp_state = temp_state
        self._worker = getattr(progress_runner, "worker", None)
        self.last_final_hdr10plus_verified = False
        self.last_sidecar_paths: list[str] = []
        self._subtitle_rules = dict(subtitle_rules or {})

        services = build_hdrplus_helper_services(
            tools=tools,
            log=self._log,
            progress_runner=progress_runner,
            temp_state=temp_state,
            subtitle_rules=self._subtitle_rules,
            run_tool_fn=lambda *args, **kwargs: run_tool(*args, **kwargs),
            log_tool_failure_fn=lambda *args, **kwargs: log_tool_failure(*args, **kwargs),
            run_mux_tool=lambda *args, **kwargs: self._run_mux_tool(*args, **kwargs),
        )
        self._subtitle_service = services.subtitle_service
        self._subtitle_mux_service = services.subtitle_mux_service
        self._hdr10plus_service = services.hdr10plus_service
        self._tool_runner = services.tool_runner
        self._mux_service = services.mux_service
        self._encode_service = services.encode_service
        self._stream_service = services.stream_service
        self._pipeline = services.pipeline

    def _log(self, msg: str, level: str = "info") -> None:
        self._log_fn(msg, level)

    def _default_encoder_config(self) -> HDRPlusEncoderConfig:
        return HDRPlusEncoderConfig.create(
            codec=self._codec,
            crf=self._crf,
            preset=self._preset,
            encoder_options=self._encoder_options,
        )

    # Diese beiden Wrapper bleiben bewusst direkt auf der Fassade. Mehrere
    # bestehende Tests/Aufrufer ersetzen den Bitstream-Service zur Laufzeit.
    def _extract_hdr10plus_metadata(self, source_stream: str, meta_json: str) -> bool:
        return self._hdr10plus_service.extract_metadata(
            self._run_hdrplus_tool_rc,
            source_stream=Path(source_stream),
            output_json=Path(meta_json),
        )

    def _inject_hdr10plus_metadata(self, encoded_hevc: str, meta_json: str, injected_hevc: str) -> bool:
        return self._hdr10plus_service.inject_metadata(
            self._run_hdrplus_tool_rc,
            input_hevc=Path(encoded_hevc),
            metadata_json=Path(meta_json),
            output_hevc=Path(injected_hevc),
        )

    def execute(self, request: PipelineExecutionRequest) -> PipelineExecutionResult:
        plan = request.plan
        if plan is None:
            return PipelineExecutionResult(
                success=False,
                failure_stage="HDR10+-Preflight",
                failure_reason="Encode-Plan fehlt.",
            )

        encoder = HDRPlusEncoderConfig.create(
            codec=request.codec,
            crf=request.crf,
            preset=request.preset,
            encoder_options=request.encoder_options,
        )
        outcome = self._run_pipeline(
            input_path=request.input_path,
            output_path=request.output_path,
            media_info=request.media_info,
            vf_args=plan.vf_args,
            audio_args=plan.audio_args,
            audio_input_args=list(getattr(plan, "audio_input_args", []) or []),
            subtitle_args=plan.sn,
            crop=plan.crop,
            container=request.container,
            override=request.override,
            encoder=encoder,
        )
        failure_reason = self._temp_state.failure_reason
        failure_stage = self._temp_state.failure_stage
        if not outcome.success and not failure_reason:
            failure_reason = "HDR10+-Pipeline fehlgeschlagen."
            failure_stage = failure_stage or "HDR10+"
        return PipelineExecutionResult(
            success=outcome.success,
            sidecar_paths=outcome.sidecar_paths,
            verified_hdr10plus=bool(outcome.success and outcome.verified_hdr10plus),
            failure_reason=failure_reason,
            failure_stage=failure_stage,
            tool_output=self._temp_state.stderr,
            tool=self._temp_state.last_tool,
            command=self._temp_state.last_command,
        )

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
        container: str = "mkv",
        override: dict | None = None,
    ) -> bool:
        outcome = self._run_pipeline(
            input_path=input_path,
            output_path=output_path,
            media_info=mi,
            vf_args=vf_args,
            audio_args=audio_args,
            audio_input_args=audio_input_args,
            subtitle_args=sn,
            crop=crop,
            container=container,
            override=override,
            encoder=self._default_encoder_config(),
        )
        return outcome.success

    def _run_pipeline(
        self,
        *,
        input_path: str,
        output_path: str,
        media_info,
        vf_args,
        audio_args,
        audio_input_args,
        subtitle_args,
        crop: str | None,
        container: str,
        override,
        encoder: HDRPlusEncoderConfig,
    ):
        self.last_final_hdr10plus_verified = False
        self.last_sidecar_paths = []
        self._temp_state.reset_diagnostics()
        context = HDRPlusExecutionContext.create(
            input_path=input_path,
            output_path=output_path,
            media_info=media_info,
            vf_args=vf_args,
            audio_args=audio_args,
            audio_input_args=audio_input_args,
            subtitle_args=subtitle_args,
            crop=crop,
            container=container,
            override=override,
            encoder=encoder,
        )
        hooks = HDRPlusPipelineHooks(
            extract_hevc_annexb=self._extract_hevc_annexb,
            extract_metadata=self._extract_hdr10plus_metadata,
            inject_metadata=self._inject_hdr10plus_metadata,
            mux_output=self._mux_hdrplus_output,
            run_mux_tool=self._run_mux_tool,
            verify_final=self._verify_final_hdr10plus,
            cleanup_tmp_sub=self._cleanup_tmp_sub,
        )
        outcome = self._pipeline.run(context, hooks)
        self.last_final_hdr10plus_verified = bool(outcome.verified_hdr10plus)
        self.last_sidecar_paths = list(outcome.sidecar_paths)
        return outcome
