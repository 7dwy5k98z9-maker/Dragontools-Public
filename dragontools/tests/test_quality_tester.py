# -*- coding: utf-8 -*-
from __future__ import annotations


def test_parse_quality_segments_supports_percent_and_timestamp_ranges():
    from dragontools.core.quality_tester import parse_quality_segments

    segments = parse_quality_segments(
        "10%+20, 00:05:00+30",
        duration_s=1000.0,
        default_duration_s=15.0,
    )

    assert len(segments) == 2
    assert segments[0].start_s == 100.0
    assert segments[0].duration_s == 20.0
    assert segments[1].start_s == 300.0
    assert segments[1].duration_s == 30.0


def test_automatic_quality_segments_are_bounded_to_video_duration():
    from dragontools.core.quality_tester import automatic_quality_segments

    segments = automatic_quality_segments(
        duration_s=60.0,
        count=3,
        segment_duration_s=20.0,
    )

    assert len(segments) == 3
    assert all(segment.start_s >= 0 for segment in segments)
    assert all(segment.start_s + segment.duration_s <= 60.0 for segment in segments)


def test_quality_run_from_dict_clamps_quality_and_fills_defaults():
    from dragontools.core.quality_tester import quality_run_from_dict

    run = quality_run_from_dict({
        "name": "CPU",
        "quality": 99,
        "encoder_options": {"encoder": "cpu", "bf": 8},
    })

    assert run.name == "CPU"
    assert run.codec == "h265"
    assert run.encoder == "cpu"
    assert run.quality == 63
    assert run.encoder_options["bf"] == 8


def test_comparison_duration_limit_respects_positive_and_negative_b_offset():
    from dragontools.core.quality_tester import comparison_duration_limit

    assert comparison_duration_limit(100.0, 95.0, 5.0) == 90.0
    assert comparison_duration_limit(100.0, 95.0, -5.0) == 95.0
    assert comparison_duration_limit(10.0, 3.0, 5.0) == 0.0


def test_comparison_segment_starts_supports_b_offset_in_both_directions():
    from dragontools.core.quality_tester import comparison_segment_starts

    assert comparison_segment_starts(20.0, 1.5) == (20.0, 21.5)
    assert comparison_segment_starts(20.0, -1.5) == (21.5, 20.0)


def test_quality_comparison_assessment_is_relative_to_reference_and_mentions_size_delta():
    from dragontools.core.quality_tester import quality_comparison_assessment

    text = quality_comparison_assessment(
        average_vmaf=97.5,
        average_ssim=0.997,
        size_a_bytes=1_000_000_000,
        size_b_bytes=700_000_000,
    )

    assert "visuell sehr nah" in text
    assert "30.0% kleiner" in text
    assert "Referenz" in text
    assert "kein automatisch bestimmter Qualitätsgewinner" in text
