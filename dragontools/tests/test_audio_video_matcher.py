# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from dragontools.core.audio_video_matcher import (
    AudioSyncPlanner,
    CutMatchResult,
    CutRegion,
    MatchPoint,
    VideoInfo,
    classify_time_mapping,
    frame_similarity,
    image_analysis_backend_label,
    opencv_available,
    parse_cut_regions,
    _signature_from_gray_frame,
)
from dragontools.core.models import AudioStream


def _info(path: str, duration: float) -> VideoInfo:
    return VideoInfo(
        path=path,
        duration_s=duration,
        audio_streams=[
            AudioStream(index=1, language="de", forced=False, title="Deutsch", codec="aac", channels=2)
        ],
    )


def _points(offset: float, times: tuple[float, ...] = (30, 120, 240, 360, 480, 570)) -> list[MatchPoint]:
    return [
        MatchPoint(reference_time_s=t, matched_time_s=t + offset, similarity=0.96, confidence=96.0)
        for t in times
    ]


def test_parse_cut_regions_accepts_comma_decimal_and_timecodes():
    regions = parse_cut_regions("1,5-2,5;01:15-01:25;01:15,500-01:25,800", duration_s=600)

    assert [(round(r.start_s, 3), round(r.end_s, 3)) for r in regions] == [
        (1.5, 2.5),
        (75.0, 85.0),
        (75.5, 85.8),
    ]


def test_opencv_signature_backend_when_available():
    if not opencv_available():
        pytest.skip("OpenCV ist optional und in dieser Umgebung nicht installiert.")

    width, height = 256, 144
    frame = bytearray(width * height)
    for y in range(20, 124):
        for x in range(30, 226):
            frame[y * width + x] = (x * 3 + y * 5) % 220 + 20

    signature = _signature_from_gray_frame(bytes(frame), width, height, 12.5)

    assert signature.backend == "opencv"
    assert signature.edge_bits == 256
    assert "OpenCV" in image_analysis_backend_label()
    assert frame_similarity(signature, signature) == pytest.approx(1.0)


def test_extra_before_and_after_source_is_case_a_not_c():
    source = _info("de.mkv", 606.0)
    target = _info("target.mkv", 600.0)
    result = classify_time_mapping(
        _points(1.0),
        source_info=source,
        target_info=target,
        expected_count=6,
    )

    assert result.mode == "A"
    assert result.can_process is True
    assert result.source_extra_start_s == 1.0
    assert result.source_extra_end_s == 5.0
    assert not result.suspect_cut_ranges


def test_linear_drift_is_case_b():
    source = _info("pal.mkv", 575.4)
    target = _info("bd.mkv", 600.0)
    points = [
        MatchPoint(reference_time_s=t, matched_time_s=t * 0.95904 + 0.4, similarity=0.97, confidence=97.0)
        for t in (30, 120, 240, 360, 480, 570)
    ]

    result = classify_time_mapping(points, source_info=source, target_info=target, expected_count=6)

    assert result.mode == "B"
    assert result.can_process is True
    assert abs(result.speed_factor - 0.95904) < 0.0001


def test_offset_jump_inside_common_content_is_case_c():
    source = _info("de.mkv", 607.0)
    target = _info("target.mkv", 600.0)
    points = [
        MatchPoint(30, 31.0, 0.96, 96.0),
        MatchPoint(120, 121.0, 0.96, 96.0),
        MatchPoint(240, 241.0, 0.96, 96.0),
        MatchPoint(360, 367.0, 0.96, 96.0),
        MatchPoint(480, 487.0, 0.96, 96.0),
        MatchPoint(570, 577.0, 0.96, 96.0),
    ]

    result = classify_time_mapping(points, source_info=source, target_info=target, expected_count=6)

    assert result.mode == "C"
    assert result.can_process is False
    assert result.suspect_cut_ranges


def test_target_extra_end_blocks_linear_audio_plan():
    source = _info("de.mkv", 595.0)
    target = _info("target.mkv", 600.0)
    result = classify_time_mapping(
        _points(0.0),
        source_info=source,
        target_info=target,
        expected_count=6,
    )

    plan = AudioSyncPlanner().build_plan(result)

    assert result.mode == "A"
    assert result.target_extra_end_s == 5.0
    assert plan.blocked is True
    assert "zusätzlichen Inhalt" in plan.block_reason


def test_case_c_plan_keeps_segments_and_removes_source_extra():
    source = _info("de.mkv", 606.0)
    target = _info("target.mkv", 600.0)
    points = _points(0.0)
    mapping = classify_time_mapping(points, source_info=source, target_info=target, expected_count=6)
    mapping.mode = "C"
    cut = CutMatchResult(
        region=CutRegion(200.0, 202.0),
        target_start_s=200.0,
        target_end_s=202.0,
        source_start_s=200.0,
        source_end_s=206.0,
        similarity_before=0.96,
        similarity_after=0.96,
        source_extra_s=4.0,
        resolved=True,
    )

    plan = AudioSyncPlanner().build_plan(mapping, cut_results=[cut])

    assert plan.blocked is False
    assert len(plan.segments) == 3
    assert plan.segments[1].target_duration_s == 2.0
    assert plan.segments[1].source_duration_s == 2.0
    assert plan.filter_kind == "filter_complex"
