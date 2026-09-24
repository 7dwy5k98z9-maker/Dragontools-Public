# -*- coding: utf-8 -*-
from __future__ import annotations

from ..core.encoder_profile_override import effective_encoder_settings
from .media_contract import build_expected_media_contract
from .quality_target_integration import apply_automatic_quality_target
from .hdr10plus_workflow_policy import should_postprocess_generated_hdr10plus
from .workflow_models import WorkflowConfig
from .workflow_override_summary import format_override_summary


class WorkflowPlanningService:
    """Erstellt Pipeline-, Encode- und Validierungsplan fuer genau eine Datei."""

    def __init__(
        self,
        *,
        config: WorkflowConfig,
        runtime_state,
        logger,
        pipeline_decision,
        encode_plan,
        standard_pipeline,
        output_paths,
        quality_target=None,
    ) -> None:
        self._config = config
        self._runtime_state = runtime_state
        self._logger = logger
        self._pipeline_decision = pipeline_decision
        self._encode_plan = encode_plan
        self._standard_pipeline = standard_pipeline
        self._output_paths = output_paths
        self._quality_target = quality_target

    def effective_strip_only(self, override: dict) -> bool:
        return bool(
            self._config.strip_only
            or override.get("processing_mode") == "strip_only"
        )

    def build_plan(self, ctx, override: dict) -> None:
        if ctx.analysis is None:
            raise RuntimeError("Analyse fehlt fuer Workflow-Plan.")
        ctx.strip_only = self.effective_strip_only(override)

        enc_settings = effective_encoder_settings(
            default_codec=self._config.codec,
            default_crf=self._config.crf,
            default_preset=self._config.preset,
            default_scale_mode=self._config.scale_mode,
            default_encoder_options=self._config.encoder_options,
            file_override=override,
        )
        ctx.effective_codec = enc_settings["codec"]
        ctx.effective_crf = enc_settings["crf"]
        ctx.effective_preset = enc_settings["preset"]
        ctx.effective_scale_mode = enc_settings["scale_mode"]
        ctx.effective_encoder_options = enc_settings["encoder_options"]
        ctx.encoder_profile_label = enc_settings["profile_label"]

        pipeline, container = self._pipeline_decision.select_pipeline_context(
            ctx.input_path, ctx.analysis, override
        )
        selection = getattr(self._pipeline_decision, "last_selection", None) or {}
        ctx.effective_preserve_dv = bool(selection.get("effective_preserve_dv", False))
        ctx.effective_preserve_hdrplus = bool(
            selection.get("effective_preserve_hdrplus", False)
        )
        ctx.generate_hdr10plus = bool(selection.get("generate_hdr10plus", False))
        ctx.generate_hdr10plus_postprocess = False
        apply_automatic_quality_target(ctx, self._quality_target)
        enc_key, q_val, q_label, preset = self._standard_pipeline.logger_start_params(
            encoder_options=ctx.effective_encoder_options,
            crf=ctx.effective_crf,
            preset=ctx.effective_preset,
        )
        self._logger.file_start(
            idx=self._runtime_state.current_idx,
            total=self._runtime_state.total_count,
            path=ctx.input_path,
            codec=ctx.effective_codec or self._config.codec,
            crf=q_val,
            preset=preset,
            encoder=enc_key,
            q_label=q_label,
            encoder_options=ctx.effective_encoder_options or self._config.encoder_options,
        )
        override_summary = format_override_summary(override, ctx.encoder_profile_label)
        if override_summary:
            self._logger.info(f"Per-Datei-Override: {override_summary}")
        pipeline_log_name = (
            "dv+hdr10+"
            if pipeline == "dv"
            and (
                ctx.generate_hdr10plus
                or (bool(getattr(ctx.analysis, "has_hdrplus", False)) and ctx.effective_preserve_hdrplus)
            )
            else "hdr10+-generated"
            if pipeline == "hdrplus" and ctx.generate_hdr10plus
            else pipeline
        )
        self._logger.pipeline(
            pipeline_log_name, container, ctx.analysis.has_dv, ctx.analysis.has_hdrplus
        )
        if ctx.strip_only and not self._config.strip_only:
            self._logger.info("Per-Datei-Modus: Nur remuxen (Strip-Only) aktiv.")

        base_dir, output_path = self._output_paths.resolve_output_path(
            ctx.input_path, container
        )
        ctx.pipeline = pipeline
        ctx.container = container
        ctx.base_dir = base_dir
        ctx.output_path = output_path

        if not ctx.strip_only:
            ctx.plan = self._encode_plan.prepare_encode_plan(
                ctx.input_path,
                output_path,
                ctx.analysis,
                pipeline,
                container,
                override,
                encoder_options=ctx.effective_encoder_options,
                scale_mode=ctx.effective_scale_mode,
                codec=ctx.effective_codec,
            )

        ctx.generate_hdr10plus_postprocess = should_postprocess_generated_hdr10plus(
            selection=selection, strip_only=ctx.strip_only, pipeline=pipeline,
            codec=ctx.effective_codec, encoder_options=ctx.effective_encoder_options,
            generate_hdr10plus=ctx.generate_hdr10plus,
        )
        if ctx.generate_hdr10plus_postprocess and not ctx.strip_only:
            self._logger.info("HDR10+: SDR→HDR-Ausgabe erhält nach dem Encode generierte dynamische Metadaten.")

        self.refresh_media_contract(
            ctx,
            override,
            crop_filter=getattr(ctx.plan, "crop", None) if ctx.plan is not None else None,
        )

    def refresh_media_contract(
        self,
        ctx,
        override: dict,
        *,
        crop_filter: str | None,
        externalized_subtitle_stream_indices=(),
    ) -> None:
        """Baut den finalen Medienvertrag mit dem tatsächlich wirksamen Crop neu.

        Im DV-Pfad kann der RPU-Level-5-Abgleich den vor dem Encode ermittelten
        AutoCrop noch ersetzen oder entfernen. Der Verifier muss deshalb den
        finalen Crop kennen, insbesondere bei der Downscale-only-Policy.
        """
        ctx.expected_media_contract = build_expected_media_contract(
            media_info=ctx.analysis,
            file_override=override,
            container=ctx.container,
            pipeline=ctx.pipeline,
            strip_only=ctx.strip_only,
            effective_codec=ctx.effective_codec or self._config.codec,
            effective_preserve_hdrplus=ctx.effective_preserve_hdrplus,
            generate_hdr10plus=bool(
                ctx.generate_hdr10plus or getattr(ctx, "generate_hdr10plus_postprocess", False)
            ),
            force_hdr_output=bool((ctx.effective_encoder_options or {}).get("_sdr_hdr_applied", False)),
            subtitle_rules=self._config.subtitle_rules,
            effective_scale_mode=ctx.effective_scale_mode,
            crop_filter=crop_filter,
            externalized_subtitle_stream_indices=externalized_subtitle_stream_indices,
        )
