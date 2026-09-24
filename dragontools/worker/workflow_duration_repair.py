# -*- coding: utf-8 -*-
"""Duration/timestamp repair orchestration extracted from verification facade."""
from __future__ import annotations


def try_duration_repair(ctx, result, source_has_audio: bool, repair_service):
    if repair_service is None or not repair_service.can_repair(
        output_path=ctx.output_path, container=ctx.container, verify_result=result
    ):
        return result

    outcome = repair_service.repair(
        output_path=ctx.output_path,
        base_dir=ctx.base_dir,
        container=ctx.container,
        expected_duration_ms=ctx.duration_ms,
        source_has_audio=source_has_audio,
        initial_result=result,
        expected_contract=getattr(ctx, "expected_media_contract", None),
        verified_hdr10plus=bool(getattr(ctx, "pipeline_verified_hdr10plus", False)),
        verified_dolby_vision=bool(getattr(ctx, "pipeline_verified_dolby_vision", False)),
        source_path=getattr(ctx, "input_path", None),
    )
    ctx.duration_repair_attempted = bool(getattr(outcome, "attempted", False))
    ctx.duration_after_ffmpeg_s = getattr(result, "duration_s", None)
    ctx.duration_after_remux_s = getattr(outcome, "remux_duration_s", None)
    ctx.duration_after_timestamp_fix_s = getattr(outcome, "timestamp_duration_s", None)
    timestamp_fixed = bool(getattr(outcome, "timestamp_fixed", False))
    remux_fixed = bool(getattr(outcome, "repaired", False)) and not timestamp_fixed
    ctx.duration_repair_method = "timestamp" if timestamp_fixed else ("remux" if remux_fixed else "")
    ctx.duration_repair_reason = str(getattr(outcome, "timestamp_repair_reason", "") or "")
    repair_command = getattr(outcome, "timestamp_repair_cmd", None) or getattr(outcome, "timestamp_ffmpeg_cmd", None)
    ctx.duration_repair_command = repair_command
    ctx.duration_repair_ffmpeg_cmd = repair_command
    ctx.duration_repair_timing_summary = getattr(outcome, "timing_summary", None)
    archive_path = getattr(outcome, "archived_path", None)
    ctx.duration_repair_archive_path = archive_path
    ctx.keep_failed_output = bool(getattr(outcome, "keep_failed_output", False))
    repaired_result = getattr(outcome, "verify_result", None) or result
    messages = list(getattr(repaired_result, "messages", []) or [])
    outcome_message = str(getattr(outcome, "message", "") or "")
    if outcome_message and outcome_message not in messages:
        messages.append(outcome_message)
    if archive_path:
        archive_message = f"Fehlerhafte Ausgabedatei wurde archiviert: {archive_path}"
        if archive_message not in messages:
            messages.append(archive_message)

    if bool(getattr(outcome, "attempted", False)) and not bool(getattr(outcome, "repaired", False)):
        ctx.duration_repair_failed_closed = True
        repaired_result.duration_ok = False
        blocked_message = (
            "Automatische Laufzeit-/Timestamp-Reparatur wurde verworfen; Output bleibt ungueltig. "
            "Replace, Postprocessing, Trickplay, Datenbank-Update und Verschieben werden gestoppt."
        )
        if blocked_message not in messages:
            messages.append(blocked_message)
    else:
        ctx.duration_repair_failed_closed = False

    repaired_result.messages = messages
    return repaired_result
