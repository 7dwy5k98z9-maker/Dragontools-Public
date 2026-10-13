"""Validate video length separately from an independently known audio tail."""
from __future__ import annotations

from ..core.media_duration import positive_seconds, stream_duration


def output_duration_plausible(probe, *, expected_duration_ms, expected_contract, plausible):
    videos = probe.video_streams
    writer = getattr(probe, "writing_application", "")
    video_duration = stream_duration(videos[0], writing_application=writer) if videos else None
    if expected_duration_ms and video_duration is not None and not plausible(
        video_duration, expected_duration_ms=expected_duration_ms
    ):
        return False
    if plausible(probe.duration_s, expected_duration_ms=expected_duration_ms):
        return True
    # A container can legitimately end after its video. Never infer permission
    # from the output alone: require the selected source-audio duration and an
    # independently matching video timeline. Other paths keep the strict gate.
    if not expected_duration_ms or video_duration is None or expected_contract is None:
        return False
    audios = probe.audio_streams
    tracks = expected_contract.audio_tracks
    if not tracks or len(audios) != len(tracks):
        return False
    references = []
    for stream, track in zip(audios, tracks):
        reference = positive_seconds(getattr(track, "duration_s", None))
        actual = stream_duration(stream, writing_application=writer)
        if reference is None or reference >= 1_000_000 or actual is None:
            return False
        if not plausible(actual, expected_duration_ms=reference * 1000):
            return False
        references.append(reference)
    container_reference = max(expected_duration_ms / 1000.0, *references)
    return plausible(probe.duration_s, expected_duration_ms=container_reference * 1000)
