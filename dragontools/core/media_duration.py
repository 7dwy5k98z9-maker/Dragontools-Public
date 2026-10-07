"""Cheap source-duration selection; never use this to validate an output.

Output verification must continue checking the actual container duration so a
damaged container cannot be hidden by a healthy video duration.
"""
from __future__ import annotations

import math
from fractions import Fraction
from .type_utils import _safe_bool

TIMESTAMP_WRAP_SECONDS = (2 ** 32) / 1000.0


def positive_seconds(value) -> float | None:
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def timestamp_wrap(expected, actual) -> tuple[int, float] | None:
    """Return positive wrap count and signed residual (seconds), not a repair."""
    expected, actual = positive_seconds(expected), positive_seconds(actual)
    if expected is None or actual is None:
        return None
    difference = actual - expected
    count = round(difference / TIMESTAMP_WRAP_SECONDS)
    residual = difference - count * TIMESTAMP_WRAP_SECONDS
    if count >= 1 and abs(residual) <= 2.0:
        return count, residual
    return None


def _plausible(value) -> float | None:
    number = positive_seconds(value)
    # Existing repair treats million-second movie timelines as extreme. Do not
    # turn such a source header into the expected duration of a normal encode.
    return number if number is not None and number < 1_000_000 else None


def stream_duration(stream: dict) -> float | None:
    if not isinstance(stream, dict):
        return None
    duration = positive_seconds(stream.get("duration"))
    if duration is not None:
        return duration
    try:
        ticks = positive_seconds(stream.get("duration_ts"))
        time_base = Fraction(str(stream.get("time_base") or "0"))
        if ticks is not None and time_base > 0:
            return positive_seconds(ticks * time_base)
    except (ValueError, ZeroDivisionError, OverflowError):
        pass
    # Matroska DURATION is an endpoint, not a length when start_time != 0.
    tags_raw = stream.get("tags") or {}
    tags = tags_raw if isinstance(tags_raw, dict) else {}
    tag = tags.get("DURATION")
    if tag:
        try:
            hours, minutes, seconds = str(tag).split(":")
            end = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
            start = float(stream.get("start_time") or 0)
            return positive_seconds(end - start)
        except (ValueError, TypeError, OverflowError):
            pass
    return None


def _probe_tracks(payload):
    streams = payload.get("streams") or []
    return [stream for stream in streams if isinstance(stream, dict)] if isinstance(streams, list) else []


def _is_real_video(stream):
    disposition = stream.get("disposition")
    flags = disposition if isinstance(disposition, dict) else {}
    return stream.get("codec_type") == "video" and not _safe_bool(flags.get("attached_pic"))


def _video_duration_reference(streams, video_streams):
    primary = next((s for s in streams if _is_real_video(s)), None)
    measured = _plausible(stream_duration(primary)) if primary else None
    if measured is not None:
        return measured
    models = {getattr(s, "index", None): s for s in video_streams}
    model = models.get(primary.get("index")) if primary else next(iter(video_streams), None)
    return _plausible(getattr(model, "duration_s", None))


def _audio_duration_reference(streams, audio_streams, container):
    raw = [d for s in streams if s.get("codec_type") == "audio"
           if (d := _plausible(stream_duration(s))) is not None]
    models = [d for s in audio_streams if (d := _plausible(getattr(s, "duration_s", None))) is not None]
    candidates = raw or models
    if container is not None and candidates:
        return min(candidates, key=lambda value: abs(value - container))
    return max(candidates, default=None)


def source_duration(payload: dict, *, video_streams=(), audio_streams=(), container_duration=None) -> float | None:
    """Choose the primary real video duration, using independent fallback evidence.

    No FPS multiplication; only agreeing container/audio evidence can reject a
    wildly conflicting video header. Output validation must still check the
    actual container duration independently of this source-reference policy.
    """
    payload = payload if isinstance(payload, dict) else {}
    streams = _probe_tracks(payload)
    raw_format = payload.get("format")
    fmt = raw_format if isinstance(raw_format, dict) else {}
    container = _plausible(fmt.get("duration")) or _plausible(container_duration)
    video = _video_duration_reference(streams, video_streams)
    audio = _audio_duration_reference(streams, audio_streams, container)
    if video and container and audio:
        extreme = max(video, container) >= 2 * min(video, container) and abs(video - container) >= 120
        if extreme and abs(audio - container) <= max(3, container * .02):
            return container
    return video or container or audio
