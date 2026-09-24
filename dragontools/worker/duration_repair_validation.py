# -*- coding: utf-8 -*-
from __future__ import annotations

from .duration_repair_models import (
    MediaTimingInfo,
    calculate_expected_duration,
    detect_timestamp_problem,
)
from .workflow_engine import WorkflowVerifyResult


_REPAIR_DURATION_TOLERANCE_S = 0.4


def _repair_duration_close(value: float | None, expected: float | None, *, tolerance_s: float = _REPAIR_DURATION_TOLERANCE_S) -> bool:
    if value is None or expected is None or value <= 0 or expected <= 0:
        return False
    return abs(float(value) - float(expected)) <= float(tolerance_s)


def _verify_message_is_stream_presence(message: str, ignored_kinds: set[str]) -> bool:
    text = str(message or "")
    if "video" in ignored_kinds and (
        "Kein Videostream" in text or "Videostream-Anzahl abweichend" in text
    ):
        return True
    if "audio" in ignored_kinds and (
        "Quelle hatte Audio" in text or "Audiospur-Anzahl abweichend" in text
    ):
        return True
    if "subtitle" in ignored_kinds and "Untertitelspur-Anzahl abweichend" in text:
        return True
    return False


def validate_timestamp_repair(
    *,
    before: MediaTimingInfo,
    repaired: MediaTimingInfo,
    verify_result: WorkflowVerifyResult,
    expected_duration_ms: int | None,
    source_has_audio: bool,
    stream_count_overrides: set[str] | None = None,
    ignore_verify_stream_kinds: set[str] | None = None,
) -> tuple[bool, list[str]]:
    """Validate that a timestamp rebuild preserved streams and sane timing.

    Timestamp-Reparaturen verwenden absichtlich eine enge, aber praxisnahe
    Laufzeittoleranz von 0,4 Sekunden. Stream-Presence kann durch den separaten
    3-Tool-Guard überschrieben werden; Paket-/Hashintegrität wird anschließend
    zusätzlich unabhängig geprüft.
    """
    messages: list[str] = []
    overrides = set(stream_count_overrides or ())
    ignored_verify = set(ignore_verify_stream_kinds or ())
    if not verify_result.ok:
        verify_messages = list(verify_result.messages or ["Output-Validierung fehlgeschlagen."])
        messages.extend(
            message for message in verify_messages
            if not _verify_message_is_stream_presence(message, ignored_verify)
        )

    if "video" not in overrides and repaired.video_stream_count != before.video_stream_count:
        messages.append("Videostream-Anzahl hat sich geändert.")
    if "audio" not in overrides and repaired.audio_stream_count != before.audio_stream_count:
        messages.append("Audiospur-Anzahl hat sich geändert.")
    if "subtitle" not in overrides and repaired.subtitle_stream_count != before.subtitle_stream_count:
        messages.append("Untertitelspur-Anzahl hat sich geändert.")
    if repaired.attachment_stream_count < before.attachment_stream_count:
        messages.append("Attachments oder Metadaten-Streams gingen verloren.")
    if source_has_audio and "audio" not in overrides and repaired.audio_stream_count <= 0:
        messages.append("Quelle hatte Audio, reparierte Datei enthält aber keine Audiospur.")

    expected_from_frames = calculate_expected_duration(repaired) or calculate_expected_duration(before)
    expected_from_source = expected_duration_ms / 1000.0 if expected_duration_ms else None
    reference = expected_from_source or expected_from_frames
    if reference is None:
        messages.append("Keine Referenzdauer für die reparierte Datei vorhanden.")
    else:
        if not _repair_duration_close(repaired.video_duration_s, reference):
            messages.append(
                "Reparierte Videodauer liegt außerhalb der ±0,4-s-Toleranz zur Referenzdauer."
            )
        if not _repair_duration_close(repaired.container_duration_s, reference):
            messages.append(
                "Reparierte Containerdauer liegt außerhalb der ±0,4-s-Toleranz zur Referenzdauer."
            )
        # Audiodauer ist bei beschädigten Matroska-Dateien nicht immer zuverlässig
        # als Stream-Metadatum verfügbar. Ein abweichender Duration-Wert allein
        # verwirft die Reparatur daher nicht mehr. Streamerhalt und Nutzdaten werden
        # durch 3-Tool-Inventar + Paketanzahl + SHA-256 pro Stream abgesichert.
        if expected_from_frames is not None and expected_from_source is not None:
            frame_tolerance = max(
                _REPAIR_DURATION_TOLERANCE_S,
                (1.0 / float(repaired.frame_rate or before.frame_rate)) if (repaired.frame_rate or before.frame_rate) else 0.0,
            )
            if not _repair_duration_close(expected_from_frames, expected_from_source, tolerance_s=frame_tolerance):
                messages.append(
                    "Frame/FPS-Dauer passt nicht innerhalb der Reparaturtoleranz zur Quelldauer."
                )

    if repaired.video_start_s is not None and repaired.audio_start_s is not None:
        if abs(repaired.video_start_s - repaired.audio_start_s) > 1.0:
            messages.append("Audio und Video starten nach Reparatur nicht synchron.")

    after_problem = detect_timestamp_problem(repaired, expected_duration_s=expected_from_source)
    if after_problem.should_repair:
        messages.append("Reparierte Datei zeigt weiterhin einen extremen Timestamp-Ausreißer.")

    return not messages, messages
