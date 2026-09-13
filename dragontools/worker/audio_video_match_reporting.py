# -*- coding: utf-8 -*-
"""Pure formatting/reporting helpers for the audio/video matcher worker."""
from __future__ import annotations

from collections.abc import Callable

from ..core.audio_video_matcher import AudioSyncPlan, TimeMappingResult, format_seconds

LogLine = Callable[[str], None]


def log_analysis_result(result: TimeMappingResult, emit: LogLine) -> None:
    mode_label = {
        "A": "Fall A – reiner Offset",
        "B": "Fall B – Offset + lineare Drift",
        "C": "Fall C – unterschiedliche Schnitte",
        "D": "Fehlerfall / kein sicheres Match",
    }.get(result.mode, result.mode)
    emit(f"✅ Analyse abgeschlossen: {mode_label}")
    emit(f"ℹ️  Startoffset: {result.offset_s:+.3f}s")
    emit(f"ℹ️  Geschwindigkeitsfaktor: {result.speed_factor:.8f}")
    emit(f"ℹ️  Drift: {result.drift_s:.3f}s | Modellfehler: {result.residual_error_s:.3f}s")
    emit(f"ℹ️  Match-Sicherheit: {result.confidence_percent:.1f}%")
    emit(
        "ℹ️  Gemeinsamer Bereich Zielvideo: "
        f"{format_seconds(result.common_start_target_s)}-{format_seconds(result.common_end_target_s)}"
    )
    for warning in result.warnings:
        emit(f"⚠️  {warning}")
    if result.suspect_cut_ranges:
        pretty = "; ".join(
            f"{format_seconds(region.start_s)}-{format_seconds(region.end_s)}"
            for region in result.suspect_cut_ranges
        )
        emit(f"⚠️  Verdächtige Schnittbereiche: {pretty}")


def log_plan(plan: AudioSyncPlan, emit: LogLine) -> None:
    if plan.blocked:
        emit(f"❌ Audio-Sync-Plan blockiert: {plan.block_reason}")
        return
    emit(
        f"ℹ️  Audio-Sync-Plan: {len(plan.segments)} Segment(e), "
        f"{plan.target_codec} {plan.target_bitrate}"
    )
    for idx, segment in enumerate(plan.segments, start=1):
        emit(
            f"ℹ️    Segment {idx}: Ziel {format_seconds(segment.target_start_s)}-"
            f"{format_seconds(segment.target_end_s)} → Quelle "
            f"{format_seconds(segment.source_start_s)}-{format_seconds(segment.source_end_s)}"
        )
    for warning in plan.warnings:
        emit(f"⚠️  {warning}")


__all__ = ["log_analysis_result", "log_plan"]
