# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import TYPE_CHECKING

from ..core.error_report import write_conversion_error_report
from .workflow_models import PipelineExecutionRequest, WorkflowConfig

if TYPE_CHECKING:
    from .workflow_engine import WorkflowContext


class WorkflowServices:
    """Schlanke Fassade fuer den Converter-Workflow.

    Die fachlichen Verantwortlichkeiten sind bewusst getrennt:

    * ``WorkflowPlanningService`` erstellt Pipeline-/Encode-/Medienvertrag.
    * ``WorkflowPipelineExecutor`` fuehrt eine Pipeline ueber Request/Result aus.
    * ``WorkflowVerificationService`` validiert und repariert den Output.
    * ``WorkflowOutputCommitCoordinator`` committed Video/Sidecars/Postprocess.

    Diese Klasse verbindet die Komponenten nur noch mit der WorkflowEngine und
    besitzt keine Kenntnis privater Pipeline-Implementierungsdetails.
    """

    def __init__(
        self,
        *,
        config: WorkflowConfig,
        temp_state,
        logger,
        media_analysis,
        planning_service,
        pipeline_executor,
        verification_service,
        output_commit,
        cleanup_service,
        result_service,
    ) -> None:
        self._config = config
        self._temp_state = temp_state
        self._logger = logger
        self._media_analysis = media_analysis
        self._planning = planning_service
        self._pipeline_executor = pipeline_executor
        self._verification = verification_service
        self._output_commit = output_commit
        self._cleanup_service = cleanup_service
        self._result_service = result_service

    @property
    def _strip_only(self) -> bool:
        return self._config.strip_only

    def _effective_strip_only(self, override: dict) -> bool:
        """Kompatible kleine API fuer Queue-/Regressionstests."""
        return bool(
            self._config.strip_only
            or override.get("processing_mode") == "strip_only"
        )

    def analyze(self, ctx: "WorkflowContext") -> None:
        ctx.analysis, ctx.duration_ms, ctx.size_before = self._media_analysis.analyze(
            ctx.input_path
        )

    def build_plan(self, ctx: "WorkflowContext", override: dict) -> None:
        self._planning.build_plan(ctx, override)

    def process(self, ctx: "WorkflowContext", override: dict) -> None:
        request = PipelineExecutionRequest.from_context(ctx, override)
        ctx.strategy_name = "strip_only" if request.strip_only else request.pipeline

        if request.pipeline == "standard" and getattr(ctx.analysis, "has_dv", False):
            self._logger.info(
                "STANDARD-Modus: Dolby Vision wird entfernt; "
                "HDR10-Basis bleibt erhalten, wenn vorhanden."
            )

        result = self._pipeline_executor.execute(request)
        if (
            not result.success
            and request.pipeline == "dv"
            and (result.failure_reason == "DV_DISABLED_BY_USER_CROP" or self._temp_state.failure_reason == "DV_DISABLED_BY_USER_CROP")
        ):
            self._logger.info(
                "ℹ️ DV wurde im Crop-Konfliktdialog deaktiviert – Datei wird mit gleicher "
                "Konfiguration ohne Dolby-Vision-Erhalt neu geplant."
            )
            fallback_override = dict(override or {})
            fallback_override["preserve_dv"] = False
            self._temp_state.reset_diagnostics()
            self._planning.build_plan(ctx, fallback_override)
            request = PipelineExecutionRequest.from_context(ctx, fallback_override)
            ctx.strategy_name = request.pipeline
            result = self._pipeline_executor.execute(request)

        ctx.sidecar_paths = list(result.sidecar_paths)
        ctx.pipeline_verified_hdr10plus = bool(result.verified_hdr10plus)
        ctx.pipeline_verified_dolby_vision = bool(result.verified_dolby_vision)
        if result.success:
            if request.pipeline == "dv" and bool(getattr(result, "effective_crop_known", False)):
                self._planning.refresh_media_contract(
                    ctx,
                    override,
                    crop_filter=getattr(result, "effective_crop", None),
                )
            return

        failure_reason = result.failure_reason or self._temp_state.failure_reason
        failure_stage = result.failure_stage or self._temp_state.failure_stage
        last_output = result.tool_output or self._temp_state.stderr
        ctx.pipeline_failure_reason = failure_reason
        ctx.pipeline_failure_stage = failure_stage
        ctx.pipeline_failure_tool = result.tool or self._temp_state.last_tool
        ctx.pipeline_failure_command = result.command or self._temp_state.last_command

        if last_output:
            self._logger.error("Letzte Tool-Ausgabe:")
            for line in last_output.splitlines()[-8:]:
                self._logger.error(f"  {line}")

        detail = failure_reason.strip()
        if failure_stage and failure_stage not in detail:
            detail = f"{failure_stage}: {detail}" if detail else failure_stage
        message = f"Pipeline-Ausfuehrung fehlgeschlagen ({ctx.strategy_name})"
        if detail:
            message += f": {detail}"
        raise RuntimeError(message)

    def verify(self, ctx: "WorkflowContext") -> None:
        self._verification.verify(ctx)

    def replace(self, ctx: "WorkflowContext") -> None:
        self._output_commit.replace(ctx)

    # Bewusst kleine Delegates: bestehende gezielte Tests/Debug-Hooks koennen
    # die Commit-Komponente ueber die Workflow-Fassade weiterhin erreichen,
    # ohne dass die Implementierung wieder in diese Klasse zurueckwandert.
    def _finalize_sidecars(self, ctx: "WorkflowContext") -> None:
        self._output_commit.finalize_sidecars(ctx)

    def _start_postprocess(self, ctx: "WorkflowContext") -> bool:
        return self._output_commit.start_postprocess(ctx)

    def finalize(self, ctx: "WorkflowContext") -> None:
        if getattr(ctx, "postprocess_pending", False) and hasattr(
            self._result_service,
            "finalize_success_pending_postprocess",
        ):
            self._result_service.finalize_success_pending_postprocess(ctx)
        else:
            self._result_service.finalize_success(ctx)

    def finalize_blocked(self, ctx: "WorkflowContext") -> None:
        self._result_service.finalize_blocked(ctx)

    def finalize_cleanup_pending(self, ctx: "WorkflowContext") -> None:
        self._result_service.finalize_cleanup_pending(ctx)

    def fail(self, ctx: "WorkflowContext", reason: str, traceback_text: str = "") -> None:
        try:
            if not hasattr(ctx, "strip_only"):
                ctx.strip_only = bool(self._strip_only)
            ctx.error_report_path = write_conversion_error_report(
                ctx=ctx,
                reason=reason,
                tool_output=getattr(self._temp_state, "stderr", "") or "",
                log_file=getattr(self._logger, "log_file", None),
                traceback_text=traceback_text,
            )
        except Exception as exc:
            self._logger.error(f"Fehlerbericht konnte nicht erstellt werden: {exc}")
        self._result_service.fail(ctx, reason)

    def cleanup(self, ctx: "WorkflowContext") -> None:
        self._cleanup_service.cleanup_temp_artifacts(
            burn_sub_tmp=self._temp_state.burn_sub_tmp,
            base_dir=ctx.base_dir,
            output_path=ctx.output_path,
            sidecar_paths=ctx.sidecar_paths,
            keep_output=ctx.success or bool(getattr(ctx, "keep_failed_output", False)),
        )
        self._temp_state.burn_sub_tmp = None


__all__ = ["WorkflowConfig", "WorkflowServices"]
