# -*- coding: utf-8 -*-
from __future__ import annotations

from .dv_workflow_pipeline_adapter import DVPipelineExecutorAdapter
from .workflow_models import WorkflowConfig
from .workflow_output_commit import WorkflowOutputCommitCoordinator
from .workflow_pipeline_executor import WorkflowPipelineExecutor
from .workflow_planning_service import WorkflowPlanningService
from .workflow_services import WorkflowServices
from .workflow_verification_service import WorkflowVerificationService


def build_workflow_services(
    *,
    services,
    job,
    runtime_state,
    temp_state,
    session_state,
    logger,
) -> WorkflowServices:
    """Verdrahtet Workflow-Komponenten ohne Zugriff auf private Worker-Felder."""
    config = WorkflowConfig(
        codec=job.codec,
        crf=job.crf,
        preset=job.preset,
        scale_mode=job.scale_mode,
        encoder_options=dict(job.encoder_options),
        strip_only=job.strip_only,
        subtitle_rules=dict(job.subtitle_rules or {}),
    )
    planning = WorkflowPlanningService(
        config=config,
        runtime_state=runtime_state,
        logger=logger,
        pipeline_decision=services.pipeline_decision,
        encode_plan=services.encode_plan,
        standard_pipeline=services.standard_pipeline,
        output_paths=services.output_paths,
    )
    pipeline_executor = WorkflowPipelineExecutor(
        standard_pipeline=services.standard_pipeline,
        strip_runner=services.strip.strip_only,
        dv_pipeline=DVPipelineExecutorAdapter(services.dv_pipeline, temp_state),
        hdrplus_pipeline=services.hdrplus,
        av1_dv_pipeline=services.av1_dv_pipeline,
        av1_hdrplus_pipeline=services.av1_hdrplus_pipeline,
        temp_state=temp_state,
    )
    verification = WorkflowVerificationService(
        output_verifier=services.output_verifier,
        duration_repair_service=services.duration_repair,
        logger=logger,
    )
    output_commit = WorkflowOutputCommitCoordinator(
        replace_service=services.replace,
        logger=logger,
        result_service=services.result,
        sidecar_outputs=session_state.sidecar_outputs,
        postprocess_outputs=session_state.postprocess_outputs,
        postprocess_service=services.postprocess,
        postprocess_coordinator=services.postprocess_coordinator,
    )
    return WorkflowServices(
        config=config,
        temp_state=temp_state,
        logger=logger,
        media_analysis=services.media_analysis,
        planning_service=planning,
        pipeline_executor=pipeline_executor,
        verification_service=verification,
        output_commit=output_commit,
        cleanup_service=services.cleanup,
        result_service=services.result,
    )
