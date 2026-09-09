# -*- coding: utf-8 -*-
from __future__ import annotations

from ..core.models import Pipeline
from .workflow_models import PipelineExecutionRequest, PipelineExecutionResult


class WorkflowPipelineExecutor:
    """Waehlt die fachliche Pipeline und fuehrt sie ueber einen stabilen Vertrag aus."""

    def __init__(
        self,
        *,
        standard_pipeline,
        strip_runner,
        dv_pipeline,
        hdrplus_pipeline,
        temp_state,
        av1_dv_pipeline=None,
        av1_hdrplus_pipeline=None,
    ) -> None:
        self._standard_pipeline = standard_pipeline
        self._strip_runner = strip_runner
        self._dv_pipeline = dv_pipeline
        self._hdrplus_pipeline = hdrplus_pipeline
        self._av1_dv_pipeline = av1_dv_pipeline
        self._av1_hdrplus_pipeline = av1_hdrplus_pipeline
        self._temp_state = temp_state

    def execute(self, request: PipelineExecutionRequest) -> PipelineExecutionResult:
        self._temp_state.reset_diagnostics()
        if request.strip_only:
            return self._execute_strip(request)

        try:
            pipeline = Pipeline(request.pipeline)
        except ValueError:
            pipeline = Pipeline.STANDARD

        if pipeline == Pipeline.DV:
            return self._dv_pipeline.execute(request)
        if pipeline == Pipeline.HDRPLUS:
            return self._hdrplus_pipeline.execute(request)
        if pipeline == Pipeline.AV1_DV:
            if self._av1_dv_pipeline is None:
                return PipelineExecutionResult(success=False, failure_stage="AV1-DV10", failure_reason="AV1-DV10-Pipeline ist nicht verdrahtet.")
            return self._av1_dv_pipeline.execute(request)
        if pipeline == Pipeline.AV1_HDRPLUS:
            if self._av1_hdrplus_pipeline is None:
                return PipelineExecutionResult(success=False, failure_stage="AV1-HDR10+", failure_reason="AV1-HDR10+-Pipeline ist nicht verdrahtet.")
            return self._av1_hdrplus_pipeline.execute(request)
        return self._standard_pipeline.execute(request)

    def _execute_strip(self, request: PipelineExecutionRequest) -> PipelineExecutionResult:
        ok = bool(
            self._strip_runner(
                request.input_path,
                request.output_path,
                request.media_info,
                request.override,
                request.container,
            )
        )
        if ok:
            owner = getattr(self._strip_runner, "__self__", None)
            sidecars = tuple(getattr(owner, "last_sidecar_paths", ()) or ())
            return PipelineExecutionResult.succeeded(sidecar_paths=sidecars)
        return PipelineExecutionResult(
            success=False,
            failure_reason=self._temp_state.failure_reason,
            failure_stage=self._temp_state.failure_stage or "Strip-Only",
            tool_output=self._temp_state.stderr,
            tool=self._temp_state.last_tool,
            command=self._temp_state.last_command,
        )
