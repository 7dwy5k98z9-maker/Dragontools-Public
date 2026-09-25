# -*- coding: utf-8 -*-
from __future__ import annotations

from .duration_repair_models import (
    MediaTimingInfo,
    calculate_expected_duration,
    detect_timestamp_problem,
)
from .workflow_engine import WorkflowVerifyResult


# Patch BA: Die normale Output-Validierung darf weiterhin enger arbeiten. Für
# eine *verlustfreie* Timestamp-Reparatur ist die entscheidende Referenz aber
# die getrennt vermessene Original-Timeline. Container-/Track-Duration-Felder
# können beim Remux um einige Frames bzw. Bruchteile einer Sekunde variieren,
# obwohl alle Paketnutzdaten identisch geblieben sind.
_REPAIR_VIDEO_TOLERANCE_S = 1.0
_REPAIR_CONTAINER_TOLERANCE_S = 1.0
_LEGACY_REPAIR_TOLERANCE_S = 0.4
_EXTREME_TIMESTAMP_S = 1_000_000.0


def _repair_duration_close(value: float | None, expected: float | None, *, tolerance_s: float) -> bool:
    if value is None or expected is None or value <= 0 or expected <= 0:
        return False
    return abs(float(value) - float(expected)) <= float(tolerance_s)


def _sane_reference(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric <= 0 or numeric >= _EXTREME_TIMESTAMP_S:
        return None
    return numeric


def source_video_reference_s(
    source_reference: MediaTimingInfo | None,
    *,
    expected_duration_ms: int | None = None,
    fallback_info: MediaTimingInfo | None = None,
) -> float | None:
    """Return the most specific trustworthy source-video duration.

    Priority is deliberately video-specific. The old implementation compared
    the repaired video against one global source duration that had been built
    from ``max(container, video, audio, subtitles)``. That can reject a correct
    timestamp repair when a subtitle/chapter/container duration ends later than
    the actual video track.
    """
    if source_reference is not None:
        for value in (
            source_reference.video_duration_s,
            calculate_expected_duration(source_reference),
            source_reference.container_duration_s,
        ):
            sane = _sane_reference(value)
            if sane is not None:
                return sane
    if fallback_info is not None:
        sane = _sane_reference(calculate_expected_duration(fallback_info))
        if sane is not None:
            return sane
    if expected_duration_ms and expected_duration_ms > 0:
        return _sane_reference(float(expected_duration_ms) / 1000.0)
    return None


def source_container_reference_s(
    source_reference: MediaTimingInfo | None,
    *,
    expected_duration_ms: int | None = None,
    video_reference_s: float | None = None,
) -> float | None:
    if source_reference is not None:
        sane = _sane_reference(source_reference.container_duration_s)
        if sane is not None:
            return sane
    if expected_duration_ms and expected_duration_ms > 0:
        sane = _sane_reference(float(expected_duration_ms) / 1000.0)
        if sane is not None:
            return sane
    return _sane_reference(video_reference_s)


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
    source_reference: MediaTimingInfo | None = None,
) -> tuple[bool, list[str]]:
    """Validate that a lossless timestamp rebuild preserved streams and timing.

    Patch BA separates the source references:

    * repaired video is compared with the source *video* timeline;
    * repaired container is compared with the source *container* timeline;
    * one-frame / sub-second differences are tolerated up to 1.0 s;
    * packet count + SHA-256 payload checks remain the hard lossless guard.

    If an original-source timing reference is unavailable, the function falls
    back to the older global duration reference for compatibility.
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

    video_reference = source_video_reference_s(
        source_reference,
        expected_duration_ms=expected_duration_ms,
        fallback_info=before,
    )
    container_reference = source_container_reference_s(
        source_reference,
        expected_duration_ms=expected_duration_ms,
        video_reference_s=video_reference,
    )

    if video_reference is None and container_reference is None:
        messages.append("Keine Referenzdauer für die reparierte Datei vorhanden.")
    else:
        if video_reference is not None and not _repair_duration_close(
            repaired.video_duration_s,
            video_reference,
            tolerance_s=_REPAIR_VIDEO_TOLERANCE_S,
        ):
            messages.append(
                "Reparierte Videodauer liegt außerhalb der ±1,0-s-Toleranz zur Original-Videoreferenz."
            )
        if container_reference is not None and not _repair_duration_close(
            repaired.container_duration_s,
            container_reference,
            tolerance_s=_REPAIR_CONTAINER_TOLERANCE_S,
        ):
            messages.append(
                "Reparierte Containerdauer liegt außerhalb der ±1,0-s-Toleranz zur Original-Containerreferenz."
            )

        # Compare frame/FPS duration with a video-specific source reference, not
        # with the old max-of-all-streams duration. A single-frame difference is
        # explicitly tolerated; the repair itself must still preserve the
        # already encoded packet count exactly (checked separately by SHA-256).
        repaired_frame_duration = calculate_expected_duration(repaired)
        source_frame_duration = calculate_expected_duration(source_reference) if source_reference is not None else None
        frame_reference = _sane_reference(source_frame_duration) or video_reference
        if repaired_frame_duration is not None and frame_reference is not None:
            rate = repaired.frame_rate or (source_reference.frame_rate if source_reference else None) or before.frame_rate
            one_frame_s = (1.0 / float(rate)) if rate else 0.0
            frame_tolerance = max(_REPAIR_VIDEO_TOLERANCE_S, one_frame_s)
            if not _repair_duration_close(
                repaired_frame_duration,
                frame_reference,
                tolerance_s=frame_tolerance,
            ):
                messages.append(
                    "Frame/FPS-Dauer passt nicht innerhalb der ±1,0-s-/1-Frame-Toleranz zur Original-Videoreferenz."
                )

    if repaired.video_start_s is not None and repaired.audio_start_s is not None:
        if abs(repaired.video_start_s - repaired.audio_start_s) > 1.0:
            messages.append("Audio und Video starten nach Reparatur nicht synchron.")

    # For the post-repair extreme-timestamp test use the actual source-video
    # reference whenever possible. The old global source duration remains only
    # a compatibility fallback.
    after_problem = detect_timestamp_problem(repaired, expected_duration_s=video_reference)
    if after_problem.should_repair:
        messages.append("Reparierte Datei zeigt weiterhin einen extremen Timestamp-Ausreißer.")

    return not messages, messages


__all__ = [
    "validate_timestamp_repair",
    "source_video_reference_s",
    "source_container_reference_s",
]
