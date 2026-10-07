# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import TYPE_CHECKING

from ..core.error_report import write_conversion_error_report
from .workflow_models import PipelineExecutionRequest, WorkflowConfig
from .mp4_default_flags import finalize_mp4_defaults

if TYPE_CHECKING:
    from .workflow_engine import WorkflowContext


from .dv_source_rpu_fallback import is_corrupt_source_rpu_failure as _is_corrupt_source_rpu_failure


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
        abort_check=None,
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
        self._abort_check = abort_check or (lambda: False)

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
        start_nfo = getattr(self._output_commit, "start_nfo_during_conversion", None)
        if callable(start_nfo):
            start_nfo(ctx)


    def _execute_without_dv(
        self,
        ctx: "WorkflowContext",
        execution_override: dict,
    ):
        """Replan and execute one recovery attempt with only DV disabled.

        Other dynamic-HDR policy is deliberately left untouched.  In
        particular, an HDR10+ source (or an explicitly requested HDR10+
        generation path) may still select the HDR10+ pipeline after DV is
        disabled for a corrupt source RPU.
        """
        if getattr(self,'_abort_check',lambda: False)():
            from .workflow_models import PipelineExecutionResult
            return PipelineExecutionRequest.from_context(ctx, execution_override), PipelineExecutionResult(
                False,failure_reason='Abgebrochen vor DV-Fallback.',failure_stage='DV-Fallback Cancel')
        execution_override["preserve_dv"] = False
        self._temp_state.reset_diagnostics()
        self._planning.build_plan(ctx, execution_override)
        request = PipelineExecutionRequest.from_context(ctx, execution_override)
        ctx.strategy_name = request.pipeline
        return request, self._pipeline_executor.execute(request)

    def _dv_disabled_by_crop(self, request, result) -> bool:
        return bool(
            request.pipeline == "dv"
            and (
                result.failure_reason == "DV_DISABLED_BY_USER_CROP"
                or self._temp_state.failure_reason == "DV_DISABLED_BY_USER_CROP"
            )
        )

    def _corrupt_source_rpu_requires_fallback(self, request, result) -> bool:
        return bool(
            request.pipeline in {"dv", "av1_dv"}
            and bool(getattr(self._config,'corrupt_source_rpu_fallback',True))
            and _is_corrupt_source_rpu_failure(result, self._temp_state)
        )

    def _apply_pipeline_result_state(self, ctx: "WorkflowContext", result) -> None:
        # Recovery ownership must reach cleanup before any fallible reporting.
        if bool(getattr(result, "preserve_failed_output", False)):
            ctx.keep_failed_output = True
        ctx.sidecar_paths = list(result.sidecar_paths)
        ctx.pipeline_verified_hdr10plus = bool(result.verified_hdr10plus)
        ctx.pipeline_verified_dolby_vision = bool(result.verified_dolby_vision)
        ctx.pipeline_verified_dv_crop_alignment = bool(
            getattr(result, "verified_dv_crop_alignment", False)
        )
        ctx.pipeline_final_rpu_checked = bool(getattr(result, "final_rpu_checked", False))
        ctx.pipeline_final_rpu_present = bool(getattr(result, "final_rpu_present", False))
        ctx.pipeline_final_rpu_matches_injected = getattr(result, "final_rpu_matches_injected", None)
        ctx.pipeline_final_rpu_expected_sha256 = str(getattr(result, "final_rpu_expected_sha256", "") or "")
        ctx.pipeline_final_rpu_actual_sha256 = str(getattr(result, "final_rpu_actual_sha256", "") or "")
        ctx.pipeline_final_rpu_level5_offsets = tuple(getattr(result, "final_rpu_level5_offsets", ()) or ())
        ctx.pipeline_final_rpu_level5_dynamic = bool(getattr(result, "final_rpu_level5_dynamic", False))
        ctx.pipeline_final_rpu_message = str(getattr(result, "final_rpu_message", "") or "")
        failure_archive_path = str(getattr(result, "failure_archive_path", "") or "")
        if failure_archive_path:
            ctx.replacement_archived_path = failure_archive_path
            self._logger.warn(f"📦 DV/HDR10+-Diagnosearchiv: {failure_archive_path}")

    def process(self, ctx: "WorkflowContext", override: dict) -> None:
        execution_override = dict(override or {})
        request = PipelineExecutionRequest.from_context(ctx, execution_override)
        ctx.strategy_name = "strip_only" if request.strip_only else request.pipeline

        if request.pipeline == "standard" and getattr(ctx.analysis, "has_dv", False):
            self._logger.info(
                "STANDARD-Modus: Dolby Vision wird entfernt; "
                "HDR10-Basis bleibt erhalten, wenn vorhanden."
            )

        result = self._pipeline_executor.execute(request)
        if not result.success and self._dv_disabled_by_crop(request, result):
            self._logger.info(
                "ℹ️ DV wurde im Crop-Konfliktdialog deaktiviert – Datei wird mit gleicher "
                "Konfiguration ohne Dolby-Vision-Erhalt neu geplant."
            )
            request, result = self._execute_without_dv(ctx, execution_override)
        elif not result.success and self._corrupt_source_rpu_requires_fallback(request, result):
            diagnostic = str(
                getattr(result, "tool_output", "")
                or getattr(self._temp_state, "stderr", "")
                or "Invalid RPU last byte"
            ).strip().splitlines()[-1]
            self._logger.warn(
                "⚠️ Dolby Vision wird für diese Datei deaktiviert: dovi_tool meldet bei "
                f"der Quell-RPU-Extraktion eine beschädigte/inkompatible RPU ({diagnostic}). "
                "Fallback: Datei wird ohne Dolby Vision neu geplant; HDR10+-Policy bleibt unverändert."
            )
            # Direct per-file policy has the highest precedence over an assigned
            # encoder profile, so even a profile with preserve_dv=True cannot
            # re-enable DV during this one recovery attempt.
            request, result = self._execute_without_dv(ctx, execution_override)

        self._apply_pipeline_result_state(ctx, result)
        if result.success:
            externalized_subs = tuple(getattr(result, "externalized_subtitle_stream_indices", ()) or ())
            if request.pipeline == "dv" and bool(getattr(result, "effective_crop_known", False)):
                ctx.effective_crop_filter = getattr(result, "effective_crop", None)
                if externalized_subs:
                    self._planning.refresh_media_contract(
                        ctx,
                        execution_override,
                        crop_filter=ctx.effective_crop_filter,
                        externalized_subtitle_stream_indices=externalized_subs,
                    )
                else:
                    self._planning.refresh_media_contract(
                        ctx,
                        execution_override,
                        crop_filter=ctx.effective_crop_filter,
                    )
            else:
                if getattr(ctx, "plan", None) is not None:
                    ctx.effective_crop_filter = getattr(ctx.plan, "crop", None)
                if externalized_subs:
                    self._planning.refresh_media_contract(
                        ctx,
                        execution_override,
                        crop_filter=getattr(ctx, "effective_crop_filter", None),
                        externalized_subtitle_stream_indices=externalized_subs,
                    )
            self._finalize_container_metadata(ctx)
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

    @staticmethod
    def _finalize_container_metadata(ctx) -> None:
        try:
            finalize_mp4_defaults(ctx.output_path, getattr(ctx, 'expected_media_contract', None),
                input_path=ctx.input_path)
        except (OSError, ValueError, RuntimeError):
            ctx.keep_failed_output = True
            raise

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
        # Covers analysis/encode/verification failures before the normal output
        # commit path had a chance to install or discard a prepared NFO.
        discard_nfo = getattr(self._output_commit, "discard_prepared_nfo", None)
        if callable(discard_nfo):
            discard_nfo(ctx)
        self._cleanup_service.cleanup_temp_artifacts(
            burn_sub_tmp=self._temp_state.burn_sub_tmp,
            base_dir=ctx.base_dir,
            output_path=ctx.output_path,
            sidecar_paths=ctx.sidecar_paths,
            keep_output=ctx.success or bool(getattr(ctx, "keep_failed_output", False)),
        )
        self._temp_state.burn_sub_tmp = None


__all__ = ["WorkflowConfig", "WorkflowServices"]
