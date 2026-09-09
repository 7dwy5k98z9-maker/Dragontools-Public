# -*- coding: utf-8 -*-
from __future__ import annotations

from .dv_runtime_models import DVEncoderConfig
from .workflow_models import PipelineExecutionRequest, PipelineExecutionResult


class DVPipelineExecutorAdapter:
    """Adapter vom Workflow-Request auf die bestehende DVProcessingPipeline."""

    def __init__(self, pipeline, temp_state) -> None:
        self._pipeline = pipeline
        self._temp_state = temp_state

    def execute(self, request: PipelineExecutionRequest) -> PipelineExecutionResult:
        plan = request.plan
        if plan is None:
            return PipelineExecutionResult(
                success=False,
                failure_stage="DV-Preflight",
                failure_reason="Encode-Plan fehlt.",
            )

        self._pipeline.configure_encoder(
            DVEncoderConfig(
                codec=request.codec,
                crf=request.crf,
                preset=request.preset,
                options=dict(request.encoder_options),
            )
        )
        dv_sn = plan.sn if getattr(plan, "burn_sub_or_vf", False) else ["-sn"]
        ok = self._pipeline.run(
            input_path=request.input_path,
            output_path=request.output_path,
            mi=request.media_info,
            vf_args=plan.vf_args,
            audio_args=plan.audio_args,
            audio_input_args=list(getattr(plan, "audio_input_args", []) or []),
            sn=dv_sn,
            crop=plan.crop,
            ov=request.override,
            preserve_hdrplus=request.preserve_hdrplus,
            container=request.container,
        )
        return PipelineExecutionResult(
            success=bool(ok),
            # Fail-closed: Sidecars gehoeren nur zu einem erfolgreichen DV-Run.
            # Damit koennen selbst bei einem kuenftigen Pipeline-State-Fehler keine
            # Artefakte eines vorherigen Jobs in den Failure-Cleanup geraten.
            sidecar_paths=tuple(self._pipeline.last_sidecar_paths or ()) if ok else (),
            verified_hdr10plus=bool(
                ok and getattr(self._pipeline, "last_hdr10plus_verified", False)
            ),
            verified_dolby_vision=bool(
                ok and getattr(self._pipeline, "last_dolby_vision_verified", False)
            ),
            failure_reason=(
                self._pipeline.last_failure_reason or self._temp_state.failure_reason
            ),
            failure_stage=(
                self._pipeline.last_failure_stage or self._temp_state.failure_stage
            ),
            tool_output=self._pipeline.last_tool_output or self._temp_state.stderr,
            tool=self._temp_state.last_tool,
            command=self._temp_state.last_command,
            effective_crop=getattr(self._pipeline, "last_effective_crop", None),
            effective_crop_known=hasattr(self._pipeline, "last_effective_crop"),
        )
