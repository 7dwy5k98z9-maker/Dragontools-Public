# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _enum_value_text(value: Any) -> str:
    """Normalisiert String-Enums und Plain-Strings ohne Enum-Namensverlust."""
    return str(getattr(value, "value", value) or "")


@dataclass(frozen=True)
class WorkflowConfig:
    """Unveraenderliche Basiskonfiguration fuer einen Konvertierungslauf."""

    codec: str
    crf: int | str
    preset: str
    scale_mode: str
    encoder_options: dict
    strip_only: bool
    subtitle_rules: dict | None = None


@dataclass(frozen=True)
class PipelineExecutionRequest:
    """Expliziter Vertrag zwischen Workflow und einer Medienpipeline.

    Der Request enthaelt ausschliesslich Daten, die eine Pipeline zur Ausfuehrung
    benoetigt. Dadurch muss der Workflow weder gebundene Methoden inspizieren
    noch private Zustandsfelder konkreter Pipelineklassen veraendern.
    """

    pipeline: str
    input_path: str
    output_path: str
    container: str
    media_info: Any
    plan: Any
    override: dict[str, Any]
    strip_only: bool
    duration_ms: int | None
    codec: str
    crf: int | str
    preset: str
    encoder_options: dict[str, Any] = field(default_factory=dict)
    preserve_hdrplus: bool = False

    @classmethod
    def from_context(cls, ctx: Any, override: dict[str, Any]) -> "PipelineExecutionRequest":
        output_path = getattr(ctx, "output_path", None)
        if not output_path:
            raise RuntimeError("Pipeline-Ausfuehrung ohne Output-Pfad ist unzulaessig.")
        effective_crf = getattr(ctx, "effective_crf", None)
        if effective_crf is None:
            raise RuntimeError("Pipeline-Ausfuehrung ohne effektiven CRF/Q-Wert ist unzulaessig.")
        raw_pipeline = getattr(ctx, "pipeline", "standard") or "standard"
        pipeline = raw_pipeline.value if hasattr(raw_pipeline, "value") else str(raw_pipeline)
        return cls(
            pipeline=pipeline,
            input_path=str(ctx.input_path),
            output_path=str(output_path),
            container=str(getattr(ctx, "container", "") or ""),
            media_info=ctx.analysis,
            plan=getattr(ctx, "plan", None),
            override=dict(override or {}),
            strip_only=bool(getattr(ctx, "strip_only", False)),
            duration_ms=getattr(ctx, "duration_ms", None),
            codec=_enum_value_text(getattr(ctx, "effective_codec", "")),
            crf=effective_crf,
            preset=str(getattr(ctx, "effective_preset", "") or ""),
            encoder_options=dict(getattr(ctx, "effective_encoder_options", None) or {}),
            preserve_hdrplus=bool(getattr(ctx, "effective_preserve_hdrplus", False)),
        )


@dataclass(frozen=True)
class PipelineExecutionResult:
    """Strukturiertes Ergebnis einer Pipeline-Ausfuehrung."""

    success: bool
    sidecar_paths: tuple[str, ...] = ()
    verified_hdr10plus: bool = False
    failure_reason: str = ""
    failure_stage: str = ""
    tool_output: str = ""
    tool: str = ""
    command: str = ""
    verified_dolby_vision: bool = False
    effective_crop: str | None = None
    effective_crop_known: bool = False

    @classmethod
    def succeeded(
        cls,
        *,
        sidecar_paths: list[str] | tuple[str, ...] | None = None,
        verified_hdr10plus: bool = False,
        verified_dolby_vision: bool = False,
    ) -> "PipelineExecutionResult":
        return cls(
            success=True,
            sidecar_paths=tuple(sidecar_paths or ()),
            verified_hdr10plus=bool(verified_hdr10plus),
            verified_dolby_vision=bool(verified_dolby_vision),
        )
