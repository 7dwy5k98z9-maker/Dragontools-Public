"""Cheap source-duration selection; never use this to validate an output.

Output verification must continue checking the actual container duration so a
damaged container cannot be hidden by a healthy video duration.
"""
from __future__ import annotations

import math

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
    duration = positive_seconds(stream.get("duration"))
    if duration is not None:
        return duration
    # Matroska DURATION is an endpoint, not a length when start_time != 0.
    tag = (stream.get("tags") or {}).get("DURATION")
    if tag:
        try:
            hours, minutes, seconds = str(tag).split(":")
            end = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
            start = float(stream.get("start_time") or 0)
            return positive_seconds(end - start)
        except (ValueError, TypeError, OverflowError):
            pass
    return None


def source_duration(payload: dict, *, video_streams=(), audio_streams=(), container_duration=None) -> float | None:
    """Prefer the first real video (the pipeline's v:0), not the longest track.

    No FPS multiplication: header evidence works for VFR and TS as well. Model
    durations supply MediaInfo evidence when ffprobe has no stream duration.
    """
    streams = payload.get("streams") or []
    videos = [s for s in streams if s.get("codec_type") == "video"
              and not (s.get("disposition") or {}).get("attached_pic")]
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    container = _plausible((payload.get("format") or {}).get("duration")) or _plausible(container_duration)
    model_by_index = {getattr(s, "index", None): s for s in video_streams}
    primary = videos[0] if videos else None
    video = _plausible(stream_duration(primary)) if primary else None
    if video is None:
        model = model_by_index.get(primary.get("index")) if primary else next(iter(video_streams), None)
        video = _plausible(getattr(model, "duration_s", None))
    audio = next((d for s in audios if (d := _plausible(stream_duration(s))) is not None), None)
    if audio is None:
        audio = next((d for s in audio_streams if (d := _plausible(getattr(s, "duration_s", None))) is not None), None)
    # A wildly conflicting video header is rejected only with independent
    # container AND audio agreement; a long subtitle cannot overrule video.
    if video and container and audio:
        extreme = max(video, container) >= 2 * min(video, container) and abs(video - container) >= 120
        if extreme and abs(audio - container) <= max(3, container * .02):
            return container
    return video or container or audio
