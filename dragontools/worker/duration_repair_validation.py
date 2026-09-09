# -*- coding: utf-8 -*-
from __future__ import annotations

from .duration_repair_models import (
    MediaTimingInfo,
    calculate_expected_duration,
    detect_timestamp_problem,
    duration_close as _duration_close,
)
from .workflow_engine import WorkflowVerifyResult


def validate_timestamp_repair(
    *,
    before: MediaTimingInfo,
    repaired: MediaTimingInfo,
    verify_result: WorkflowVerifyResult,
    expected_duration_ms: int | None,
    source_has_audio: bool,
) -> tuple[bool, list[str]]:
    """Validate that a timestamp rebuild preserved streams and sane timing."""
    messages: list[str] = []
    if not verify_result.ok:
        messages.extend(list(verify_result.messages or ["Output-Validierung fehlgeschlagen."]))

    if repaired.video_stream_count != before.video_stream_count:
        messages.append("Videostream-Anzahl hat sich geändert.")
    if repaired.audio_stream_count != before.audio_stream_count:
        messages.append("Audiospur-Anzahl hat sich geändert.")
    if repaired.subtitle_stream_count != before.subtitle_stream_count:
        messages.append("Untertitelspur-Anzahl hat sich geändert.")
    if repaired.attachment_stream_count < before.attachment_stream_count:
        messages.append("Attachments oder Metadaten-Streams gingen verloren.")
    if source_has_audio and repaired.audio_stream_count <= 0:
        messages.append("Quelle hatte Audio, reparierte Datei enthält aber keine Audiospur.")

    expected_from_frames = calculate_expected_duration(repaired) or calculate_expected_duration(before)
    expected_from_source = expected_duration_ms / 1000.0 if expected_duration_ms else None
    reference = expected_from_frames or expected_from_source
    if reference is None:
        messages.append("Keine Referenzdauer für die reparierte Datei vorhanden.")
    else:
        if not _duration_close(repaired.video_duration_s, reference):
            messages.append("Reparierte Videodauer passt nicht zur Frame/FPS-Dauer.")
        if not _duration_close(repaired.container_duration_s, reference):
            messages.append("Reparierte Containerdauer passt nicht zur Referenzdauer.")
        if source_has_audio and repaired.audio_duration_s is not None and not _duration_close(
            repaired.audio_duration_s,
            reference,
            min_tolerance_s=5.0,
            relative_tolerance=0.03,
        ):
            messages.append("Reparierte Audiodauer passt nicht plausibel zur Videodauer.")
        if expected_from_source is not None and not _duration_close(reference, expected_from_source):
            messages.append("Frame/FPS-Dauer passt nicht zur Quelldauer.")

    if repaired.video_start_s is not None and repaired.audio_start_s is not None:
        if abs(repaired.video_start_s - repaired.audio_start_s) > 1.0:
            messages.append("Audio und Video starten nach Reparatur nicht synchron.")

    after_problem = detect_timestamp_problem(repaired, expected_duration_s=expected_from_source)
    if after_problem.should_repair:
        messages.append("Reparierte Datei zeigt weiterhin einen extremen Timestamp-Ausreißer.")

    return not messages, messages
