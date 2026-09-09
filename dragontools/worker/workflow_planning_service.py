# -*- coding: utf-8 -*-
from __future__ import annotations

from ..core.encoder_profile_override import effective_encoder_settings
from .media_contract import build_expected_media_contract
from .workflow_models import WorkflowConfig


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
    ) -> None:
        self._config = config
        self._runtime_state = runtime_state
        self._logger = logger
        self._pipeline_decision = pipeline_decision
        self._encode_plan = encode_plan
        self._standard_pipeline = standard_pipeline
        self._output_paths = output_paths

    def effective_strip_only(self, override: dict) -> bool:
        return bool(
            self._config.strip_only
            or override.get("processing_mode") == "strip_only"
        )

    @staticmethod
    def _format_tristate(value) -> str:
        if value is None:
            return "global"
        return "an" if bool(value) else "aus"

    @staticmethod
    def _format_override_mode(value) -> str:
        return {
            "on": "an",
            "off": "aus",
            "inherit": "global",
        }.get(str(value or "inherit").lower(), str(value or "global"))

    @classmethod
    def _format_override_summary(cls, override: dict, profile_label: str = "") -> str:
        parts: list[str] = []
        if profile_label:
            label = "Encoder-Override" if override.get("encoder_override") else "Encoderprofil"
            parts.append(f"{label}: {profile_label}")
        if override.get("processing_mode") == "strip_only":
            parts.append("Verarbeitung: Strip-Only")
        if override.get("imax"):
            parts.append("IMAX: manuell erhalten")
        if override.get("preserve_dv") is not None:
            parts.append(
                f"Dolby Vision erhalten: {cls._format_tristate(override.get('preserve_dv'))}"
            )
        if override.get("preserve_hdrplus") is not None:
            parts.append(
                f"HDR10+ erhalten: {cls._format_tristate(override.get('preserve_hdrplus'))}"
            )
        audio_tracks = list(override.get("audio_tracks") or [])
        if override.get("audio_mode") == "custom" or audio_tracks:
            parts.append(f"Audio: manuell ({len(audio_tracks)} Spur-Regel(n))")
        subtitle_tracks = list(override.get("subtitle_tracks") or [])
        if override.get("subtitle_mode") == "custom" or subtitle_tracks:
            keep_count = sum(1 for item in subtitle_tracks if item.get("keep"))
            burn_count = sum(1 for item in subtitle_tracks if item.get("burn_in"))
            parts.append(
                f"Untertitel: manuell ({keep_count} behalten, {burn_count} Burn-In)"
            )
        drc = override.get("audio_drc")
        if isinstance(drc, dict):
            parts.append(
                f"DRC/Nachtmodus: {cls._format_override_mode(drc.get('mode'))} "
                f"({drc.get('scale', 1.0)})"
            )
        loudnorm = override.get("audio_loudnorm")
        if isinstance(loudnorm, dict):
            parts.append(
                f"Lautheitsnormalisierung: {cls._format_override_mode(loudnorm.get('mode'))} "
                f"({loudnorm.get('i', -18.0)} LUFS)"
            )
        return " | ".join(parts)

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
        override_summary = self._format_override_summary(
            override, ctx.encoder_profile_label
        )
        if override_summary:
            self._logger.info(f"Per-Datei-Override: {override_summary}")
        pipeline_log_name = (
            "dv+hdr10+"
            if pipeline == "dv"
            and bool(getattr(ctx.analysis, "has_hdrplus", False))
            and ctx.effective_preserve_hdrplus
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

        self.refresh_media_contract(
            ctx,
            override,
            crop_filter=getattr(ctx.plan, "crop", None) if ctx.plan is not None else None,
        )

    def refresh_media_contract(self, ctx, override: dict, *, crop_filter: str | None) -> None:
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
            subtitle_rules=self._config.subtitle_rules,
            effective_scale_mode=ctx.effective_scale_mode,
            crop_filter=crop_filter,
        )
