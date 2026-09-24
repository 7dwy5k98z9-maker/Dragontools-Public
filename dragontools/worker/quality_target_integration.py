# -*- coding: utf-8 -*-
from __future__ import annotations


def apply_automatic_quality_target(ctx, service) -> None:
    """Wendet ein erfolgreiches VMAF-Zielergebnis ausschließlich auf den aktuellen Kontext an."""
    if service is None or bool(getattr(ctx, "strip_only", False)):
        return
    result = service.resolve(
        input_path=ctx.input_path,
        media_info=ctx.analysis,
        codec=ctx.effective_codec,
        fixed_quality=int(ctx.effective_crf or 0),
        preset=ctx.effective_preset,
        encoder_options=dict(ctx.effective_encoder_options or {}),
        scale_mode=ctx.effective_scale_mode,
    )
    ctx.quality_target_attempted = bool(result.attempted)
    ctx.quality_target_applied = bool(result.applied)
    ctx.quality_target_selected = result.selected_quality
    ctx.quality_target_vmaf = result.selected_vmaf
    ctx.quality_target_reason = str(result.reason or "")
    if not result.applied or result.selected_quality is None:
        return
    selected = int(result.selected_quality)
    ctx.effective_crf = selected
    ctx.effective_encoder_options = service.options_for_quality(
        dict(ctx.effective_encoder_options or {}), selected
    )
