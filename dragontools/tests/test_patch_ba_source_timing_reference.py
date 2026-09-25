from __future__ import annotations

from fractions import Fraction
from types import SimpleNamespace

from dragontools.worker.duration_repair_models import MediaTimingInfo
from dragontools.worker.duration_repair_validation import (
    source_container_reference_s,
    source_video_reference_s,
    validate_timestamp_repair,
)
from dragontools.worker.duration_timestamp_helpers import allow_one_frame_wrap_cfr_repair
from dragontools.worker.duration_timing_sources import TimingSourceReader
from dragontools.worker.workflow_engine import WorkflowVerifyResult


def _ok_verify(duration_s: float) -> WorkflowVerifyResult:
    return WorkflowVerifyResult(
        exists=True,
        size_ok=True,
        container_ok=True,
        probe_ok=True,
        video_ok=True,
        audio_ok=True,
        subtitle_ok=True,
        contract_ok=True,
        metadata_ok=True,
        duration_ok=True,
        duration_s=duration_s,
        video_stream_count=1,
        audio_stream_count=1,
        subtitle_stream_count=1,
        messages=[],
    )


def test_source_video_reference_is_not_global_max_duration():
    source = MediaTimingInfo(
        path="source.mkv",
        container_duration_s=101.500,
        video_duration_s=100.750,
        audio_duration_s=99.000,
        subtitle_duration_s=101.500,
        video_frame_count=2417,
        frame_rate=Fraction(24, 1),
        frame_rate_mode="CFR",
    )
    assert source_video_reference_s(source, expected_duration_ms=101_500) == 100.750
    assert source_container_reference_s(source, expected_duration_ms=101_500) == 101.500


def test_repair_accepts_subsecond_video_difference_when_source_video_reference_matches():
    # Reproduces the Supernatural class of failure: the old global source
    # duration is 0.75 s longer than the actual source video timeline.
    source = MediaTimingInfo(
        path="source.mkv",
        container_duration_s=101.500,
        video_duration_s=100.750,
        audio_duration_s=100.700,
        subtitle_duration_s=101.500,
        video_frame_count=2417,
        frame_rate=Fraction(24, 1),
        frame_rate_mode="CFR",
        video_stream_count=1,
        audio_stream_count=1,
        subtitle_stream_count=1,
    )
    before = MediaTimingInfo(
        path="broken.mkv",
        container_duration_s=4_295_068.0,
        video_duration_s=4_295_068.0,
        video_frame_count=2418,
        frame_rate=Fraction(24, 1),
        frame_rate_mode="CFR",
        video_stream_count=1,
        audio_stream_count=1,
        subtitle_stream_count=1,
    )
    repaired = MediaTimingInfo(
        path="fixed.mkv",
        container_duration_s=101.500,
        video_duration_s=100.750,
        video_frame_count=2418,  # one encoded frame more than source
        frame_rate=Fraction(24, 1),
        frame_rate_mode="CFR",
        video_stream_count=1,
        audio_stream_count=1,
        subtitle_stream_count=1,
    )

    ok, messages = validate_timestamp_repair(
        before=before,
        repaired=repaired,
        verify_result=_ok_verify(101.500),
        expected_duration_ms=101_500,  # old max(container/video/audio/subs)
        source_has_audio=True,
        stream_count_overrides={"video", "audio", "subtitle"},
        ignore_verify_stream_kinds={"video", "audio", "subtitle"},
        source_reference=source,
    )

    assert ok is True, messages


def test_repair_still_rejects_more_than_one_second_video_drift():
    source = MediaTimingInfo(
        path="source.mkv",
        container_duration_s=101.5,
        video_duration_s=100.0,
        video_frame_count=2400,
        frame_rate=Fraction(24, 1),
        frame_rate_mode="CFR",
        video_stream_count=1,
    )
    before = MediaTimingInfo(
        path="broken.mkv",
        container_duration_s=4_295_067.0,
        video_duration_s=4_295_067.0,
        video_frame_count=2400,
        frame_rate=Fraction(24, 1),
        frame_rate_mode="CFR",
        video_stream_count=1,
    )
    repaired = MediaTimingInfo(
        path="fixed.mkv",
        container_duration_s=101.5,
        video_duration_s=101.2,
        video_frame_count=2429,
        frame_rate=Fraction(24, 1),
        frame_rate_mode="CFR",
        video_stream_count=1,
    )

    ok, messages = validate_timestamp_repair(
        before=before,
        repaired=repaired,
        verify_result=_ok_verify(101.5),
        expected_duration_ms=101_500,
        source_has_audio=False,
        stream_count_overrides={"video"},
        ignore_verify_stream_kinds={"video"},
        source_reference=source,
    )

    assert ok is False
    assert any("±1,0-s-Toleranz" in message for message in messages)


def test_one_frame_wrap_guard_accepts_point_eight_seconds_with_strong_wrap_signature():
    before = MediaTimingInfo(
        path="broken.mkv",
        container_duration_s=4_297_505.5,
        video_duration_s=4_297_505.5,
        video_frame_count=60_913,
        frame_rate=Fraction(24, 1),
        frame_rate_mode="VFR",
    )
    frame_expected = before.video_frame_count / 24.0
    assert abs(frame_expected - 2538.0416667) < 0.001
    assert allow_one_frame_wrap_cfr_repair(
        before,
        expected_duration_s=2539.0,
        fallback_reason="Frameanzahl stimmt nicht überein: Original=60912, Ausgabe=60913.",
    )


def test_count_frames_probe_gets_longer_timeout():
    seen = {}

    def fake_run(command, **kwargs):
        seen["timeout"] = kwargs.get("timeout")
        return SimpleNamespace(returncode=0, stdout='{"format": {}, "streams": []}', stderr="")

    reader = TimingSourceReader(ffprobe_path="ffprobe", run_command=fake_run)
    reader.run_ffprobe_json("film.mkv", count_frames=True)
    assert seen["timeout"] == 180
