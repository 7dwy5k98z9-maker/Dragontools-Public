# -*- coding: utf-8 -*-
"""
Gemeinsame Workflow-Engine für Konvertierungsjobs.

Ablauf:
  1) analyze
  2) build_plan
  3) process (pipeline-spezifische Strategie)
  4) verify
  5) replace

Verschieben gehoert nicht zu diesem Converter-Workflow. Es passiert nach
Run-Ende gesammelt in der GUI, damit alle erfolgreichen Ausgaben gemeinsam an
den MoveThread übergeben werden können.
"""
from __future__ import annotations

import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .workflow_services import WorkflowServices


@dataclass
class WorkflowVerifyResult:
    exists: bool = False
    size_ok: bool = False
    container_ok: bool = False
    probe_ok: bool = False
    video_ok: bool = False
    audio_ok: bool = True
    subtitle_ok: bool = True
    contract_ok: bool = True
    metadata_ok: bool = True
    duration_ok: bool = False
    format_name: str = ""
    duration_s: float | None = None
    video_stream_count: int = 0
    audio_stream_count: int = 0
    subtitle_stream_count: int = 0
    attachment_stream_count: int = 0
    data_stream_count: int = 0
    video_codec: str = ""
    video_bit_depth: int | None = None
    has_hdr: bool = False
    has_dolby_vision: bool = False
    has_hdr10plus: bool = False
    messages: list[str] | None = None
    warnings: list[str] | None = None
    expected_width: int | None = None
    expected_height: int | None = None
    actual_width: int | None = None
    actual_height: int | None = None
    geometry_max_delta: int = 0
    geometry_severity: str = "exact"
    contract_non_geometry_ok: bool = True

    @property
    def ok(self) -> bool:
        return (
            self.exists
            and self.size_ok
            and self.container_ok
            and self.probe_ok
            and self.video_ok
            and self.audio_ok
            and self.subtitle_ok
            and self.contract_ok
            and self.metadata_ok
            and self.duration_ok
        )


@dataclass
class WorkflowContext:
    input_path: str
    analysis: Any = None
    duration_ms: int | None = None
    size_before: int = 0
    start_ts: float = 0.0

    pipeline: str = ""
    container: str = ""
    strategy_name: str = ""
    plan: Any = None

    effective_codec: str = ""
    effective_crf: int | None = None
    effective_preset: str = ""
    effective_scale_mode: str = ""
    effective_encoder_options: dict[str, Any] | None = None
    effective_preserve_dv: bool = False
    effective_preserve_hdrplus: bool = False
    encoder_profile_label: str = ""
    file_override: dict[str, Any] | None = None

    base_dir: Path | None = None
    output_path: str | None = None
    final_output_path: str | None = None
    sidecar_paths: list[str] | None = None
    error_report_path: str | None = None

    expected_media_contract: Any = None
    pipeline_verified_hdr10plus: bool = False
    pipeline_verified_dolby_vision: bool = False
    pipeline_verified_dv_crop_alignment: bool = False
    pipeline_final_rpu_checked: bool = False
    pipeline_final_rpu_present: bool = False
    pipeline_final_rpu_matches_injected: bool | None = None
    pipeline_final_rpu_expected_sha256: str = ""
    pipeline_final_rpu_actual_sha256: str = ""
    pipeline_final_rpu_level5_offsets: tuple[tuple[int, int, int, int], ...] = ()
    pipeline_final_rpu_level5_dynamic: bool = False
    pipeline_final_rpu_message: str = ""
    effective_crop_filter: str | None = None
    verify_result: WorkflowVerifyResult | None = None
    duration_repair_attempted: bool = False
    duration_after_ffmpeg_s: float | None = None
    duration_after_remux_s: float | None = None
    duration_after_timestamp_fix_s: float | None = None
    duration_repair_method: str = ""
    duration_repair_reason: str = ""
    duration_repair_command: list[str] | None = None
    # Legacy alias retained for compatibility with older error-report consumers.
    duration_repair_ffmpeg_cmd: list[str] | None = None
    duration_repair_timing_summary: list[str] | None = None
    duration_repair_archive_path: str | None = None
    duration_repair_failed_closed: bool = False
    keep_failed_output: bool = False
    verification_archive_required: bool = False
    verification_archive_with_postprocess: bool = False
    verification_archive_reason: str = ""
    verification_archive_tier: str = ""
    verification_archive_path: str | None = None
    verification_report_path: str | None = None
    verification_csv_path: str | None = None
    dv_rpu_alignment_checked: bool = False
    dv_rpu_alignment_ok: bool | None = None
    dv_rpu_alignment_message: str = ""
    dv_rpu_alignment_match_mode: str = ""
    replacement_blocked: bool = False
    replacement_block_reason: str = ""
    replacement_archived_path: str | None = None
    cleanup_pending: bool = False
    cleanup_pending_message: str = ""
    postprocess_pending: bool = False
    postprocess_pending_announced: bool = False
    replace_original: bool = False
    strip_only: bool = False
    pipeline_failure_reason: str = ""
    pipeline_failure_stage: str = ""
    pipeline_failure_tool: str = ""
    pipeline_failure_command: str = ""

    error: str | None = None
    success: bool = False


class ConversionWorkflowRunner:
    """Führt den gemeinsamen Job-Workflow aus."""

    def __init__(self, services: "WorkflowServices", *, replace_original: bool) -> None:
        self.services = services
        self._replace_original = replace_original

    def run(self, input_path: str, override: dict) -> bool:
        ctx = WorkflowContext(
            input_path=input_path,
            replace_original=bool(self._replace_original),
            file_override=dict(override or {}),
        )
        ctx.start_ts = time.time()
        try:
            self.analyze(ctx)
            self.build_plan(ctx, override)
            self.process(ctx, override)
            self.verify(ctx)
            self.replace(ctx)
            if ctx.replacement_blocked:
                self.services.finalize_blocked(ctx)
                return False
            if ctx.cleanup_pending:
                ctx.keep_failed_output = True
                self.services.finalize_cleanup_pending(ctx)
                return False
            ctx.success = True
            self.finalize(ctx)
            return True
        except Exception as exc:
            ctx.error = str(exc)
            self.services.fail(ctx, str(exc), traceback.format_exc())
            return False
        finally:
            self.cleanup(ctx)

    def analyze(self, ctx: WorkflowContext) -> None:
        self.services.analyze(ctx)

    def build_plan(self, ctx: WorkflowContext, override: dict) -> None:
        self.services.build_plan(ctx, override)

    def process(self, ctx: WorkflowContext, override: dict) -> None:
        self.services.process(ctx, override)

    def verify(self, ctx: WorkflowContext) -> None:
        self.services.verify(ctx)

    def replace(self, ctx: WorkflowContext) -> None:
        self.services.replace(ctx)

    def finalize(self, ctx: WorkflowContext) -> None:
        self.services.finalize(ctx)

    def cleanup(self, ctx: WorkflowContext) -> None:
        self.services.cleanup(ctx)
