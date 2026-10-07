from __future__ import annotations

from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from dragontools.core.audio_sync_planner import AudioSyncPlanner
from dragontools.core.audio_video_match_models import MatchPoint, VideoInfo
from dragontools.core.audio_video_time_mapping import classify_time_mapping
from dragontools.core.models import AudioStream
from dragontools.core.quality_tester import QualitySegment, QualityTestRun, parse_extra_args
from dragontools.worker.quality_test_service import QualityTestService


def _video(path: str, duration: float) -> VideoInfo:
    return VideoInfo(
        path=path,
        duration_s=duration,
        audio_streams=[
            AudioStream(index=1, language="de", forced=False, title="Deutsch", codec="aac", channels=2)
        ],
    )


def test_negative_linear_offset_preserves_leading_target_gap_with_silence():
    source = _video("de.mkv", 100.0)
    target = _video("target.mkv", 100.0)
    points = [
        MatchPoint(t, t - 1.0, 0.98, 98.0)
        for t in (10.0, 25.0, 40.0, 55.0, 70.0, 90.0)
    ]

    mapping = classify_time_mapping(points, source_info=source, target_info=target, expected_count=len(points))
    plan = AudioSyncPlanner().build_plan(mapping)

    assert mapping.mode == "A"
    assert mapping.can_process is True
    assert mapping.target_extra_start_s == pytest.approx(1.0)
    assert plan.blocked is False
    assert plan.segments[0].target_start_s == pytest.approx(1.0)
    assert plan.segments[0].source_start_s == pytest.approx(0.0)
    assert "adelay=1000:all=1" in plan.filter_graph


def test_quality_extra_args_strip_grouping_quotes_for_direct_subprocess_argv():
    args = parse_extra_args('-x265-params "aq-mode=3:psy-rd=2.0" -metadata "title=My Test"')

    assert args == ["-x265-params", "aq-mode=3:psy-rd=2.0", "-metadata", "title=My Test"]


def _service(tmp_path: Path) -> QualityTestService:
    return QualityTestService(
        tools=SimpleNamespace(ffmpeg="ffmpeg", ffprobe="ffprobe"),
        process_runner=SimpleNamespace(run=lambda *_args, **_kwargs: (0, "", "")),
        metrics=SimpleNamespace(measure_encoded=lambda **_kwargs: 99.0),
        log=lambda *_args, **_kwargs: None,
        progress=lambda *_args, **_kwargs: None,
        result_ready=lambda *_args, **_kwargs: None,
        is_aborted=lambda: False,
    )


def test_quality_result_rejects_nonempty_file_without_video_stream(tmp_path: Path, monkeypatch):
    service = _service(tmp_path)
    output = tmp_path / "sample.mkv"
    output.write_bytes(b"not-empty")
    monkeypatch.setattr(service, "probe_output", lambda _path: {"streams": [], "format": {"duration": "10.0"}})

    with pytest.raises(RuntimeError, match="keine Videospur"):
        service.analyze_result(
            "input.mkv",
            str(output),
            QualityTestRun(name="CPU"),
            QualitySegment(0.0, 10.0, "01"),
        )


def test_failed_quality_case_removes_partial_output(tmp_path: Path, monkeypatch):
    service = _service(tmp_path)
    run = QualityTestRun(name="CPU")
    segment = QualitySegment(0.0, 10.0, "01")
    expected = tmp_path / "input__01__CPU_cpu.mkv"

    def fake_encode(_input, output_path, _run, _segment):
        Path(output_path).write_bytes(b"partial")
        raise RuntimeError("encoder failed")

    monkeypatch.setattr(service, "encode_segment", fake_encode)
    service._run_case("input.mkv", tmp_path, run, segment)

    assert not expected.exists()


def test_duplicate_input_stems_get_distinct_stable_output_directories(tmp_path: Path):
    service = _service(tmp_path)
    a = tmp_path / "A" / "episode.mkv"
    b = tmp_path / "B" / "episode.mkv"
    counts = Counter({"episode": 2})

    name_a = service._output_directory_name(str(a), counts)
    name_b = service._output_directory_name(str(b), counts)

    assert name_a.startswith("episode__")
    assert name_b.startswith("episode__")
    assert name_a != name_b
    assert name_a == service._output_directory_name(str(a), counts)


def test_audio_plan_cannot_reopen_classifier_block_with_custom_thresholds():
    from dragontools.core.audio_video_match_models import AudioVideoMatcherSettings

    source = _video("de.mkv", 99.0)
    target = _video("target.mkv", 100.0)
    points = [MatchPoint(t, t, 0.98, 98.0) for t in (10.0, 25.0, 40.0, 55.0, 70.0, 90.0)]
    mapping = classify_time_mapping(
        points,
        source_info=source,
        target_info=target,
        expected_count=len(points),
        settings=AudioVideoMatcherSettings(target_extra_block_s=0.5),
    )

    plan = AudioSyncPlanner().build_plan(mapping)

    assert mapping.mode == "A"
    assert mapping.target_extra_end_s == pytest.approx(1.0)
    assert mapping.can_process is False
    assert plan.blocked is True


def test_case_c_target_only_material_is_fail_closed_even_if_marked_resolved():
    from dragontools.core.audio_video_match_models import CutMatchResult, CutRegion, TimeMappingResult

    source = _video("de.mkv", 100.0)
    target = _video("target.mkv", 101.0)
    mapping = TimeMappingResult(
        mode="C",
        offset_s=0.0,
        speed_factor=1.0,
        residual_error_s=0.1,
        drift_s=0.0,
        confidence_percent=98.0,
        match_points=[],
        unmatched_reference_times=[],
        source_info=source,
        target_info=target,
        can_process=False,
    )
    cut = CutMatchResult(
        region=CutRegion(40.0, 42.0),
        target_start_s=40.0,
        target_end_s=42.0,
        source_start_s=40.0,
        source_end_s=41.0,
        similarity_before=0.98,
        similarity_after=0.98,
        target_extra_s=1.0,
        resolved=True,  # defensive contract check: planner must still refuse it
    )

    plan = AudioSyncPlanner().build_plan(mapping, cut_results=[cut])

    assert plan.blocked is True
    assert "ohne deutsche Audioentsprechung" in plan.block_reason


def test_case_c_tiny_anchor_shortfall_is_padded_to_keep_following_timeline_stable():
    from dragontools.core.audio_video_match_models import CutMatchResult, CutRegion, TimeMappingResult

    source = _video("de.mkv", 100.0)
    target = _video("target.mkv", 100.0)
    mapping = TimeMappingResult(
        mode="C",
        offset_s=0.0,
        speed_factor=1.0,
        residual_error_s=0.01,
        drift_s=0.0,
        confidence_percent=98.0,
        match_points=[],
        unmatched_reference_times=[],
        source_info=source,
        target_info=target,
        can_process=False,
    )
    cut = CutMatchResult(
        region=CutRegion(40.0, 42.0),
        target_start_s=40.0,
        target_end_s=42.0,
        source_start_s=40.0,
        source_end_s=41.97,
        similarity_before=0.98,
        similarity_after=0.98,
        target_extra_s=0.03,
        resolved=True,
    )

    plan = AudioSyncPlanner().build_plan(mapping, cut_results=[cut])

    assert plan.blocked is False
    assert "apad=whole_dur=2.000" in plan.filter_graph
    assert "atrim=duration=2.000" in plan.filter_graph


def test_source_visual_sampler_routes_ffprobe_through_cancelable_worker(monkeypatch, tmp_path):
    from dragontools.worker import source_visual_sampling as sampling

    worker = object()
    calls = []

    def fake_run_tool(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return SimpleNamespace(ok=True, stdout='{"format":{"duration":"12.5"}}')

    monkeypatch.setattr(sampling, "run_tool", fake_run_tool)
    sampler = sampling.SourceVisualSampler(ffmpeg_path="ffmpeg", ffprobe_path="ffprobe", worker=worker)

    duration = sampler.probe_duration(tmp_path / "film.mkv")

    assert duration == pytest.approx(12.5)
    assert calls[0][1]["worker"] is worker
    assert calls[0][1]["abort_on_request"] is True


def test_source_visual_sampler_routes_binary_probe_through_cancelable_worker(monkeypatch, tmp_path):
    from dragontools.worker import source_visual_sampling as sampling
    from dragontools.worker.source_visual_models import SourceVisualCheckSettings

    worker = object()
    calls = []

    def fake_run_tool_bytes(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return SimpleNamespace(ok=True, stdout=b"rgb")

    monkeypatch.setattr(sampling, "run_tool_bytes", fake_run_tool_bytes)
    sampler = sampling.SourceVisualSampler(ffmpeg_path="ffmpeg", ffprobe_path="ffprobe", worker=worker)

    payload = sampler.read_single(tmp_path / "film.mkv", 5.0, SourceVisualCheckSettings(enabled=True))

    assert payload == b"rgb"
    assert calls[0][1]["worker"] is worker
    assert calls[0][1]["abort_on_request"] is True


def test_manual_source_visual_gui_dispatches_to_background_thread():
    import ast

    source_path = Path(__file__).resolve().parents[1] / "gui" / "convert_widget_source_visual_actions.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    show = next(
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_show_source_visual_check"
    )
    calls = [node for node in ast.walk(show) if isinstance(node, ast.Call)]

    assert any(isinstance(call.func, ast.Name) and call.func.id == "SourceVisualCheckThread" for call in calls)
    assert any(isinstance(call.func, ast.Attribute) and call.func.attr == "start" for call in calls)
    assert not any(isinstance(call.func, ast.Attribute) and call.func.attr == "check" for call in calls)


def test_source_visual_abort_does_not_launch_fallback_probes(monkeypatch):
    from dragontools.worker.source_visual_check import SourceVisualCheckService, SourceVisualCheckSettings

    service = SourceVisualCheckService(ffmpeg_path="ffmpeg", ffprobe_path="ffprobe")
    service._sampler.worker = SimpleNamespace(abort_requested=True)
    singles = []
    monkeypatch.setattr(service, "_read_probe_frame_group", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service, "_read_probe_frames", lambda *_args, **_kwargs: singles.append(True) or b"x")

    result = service._read_probe_frames_batch(
        Path("film.mkv"),
        [10.0, 20.0, 30.0],
        SourceVisualCheckSettings(enabled=True),
    )

    assert result == [b"", b"", b""]
    assert singles == []


def test_fractional_rate_drift_uses_time_mapping_not_integer_frame_numbers():
    source = _video("source_24000_1001.mkv", 1001.0)
    target = _video("target_24.mkv", 1000.0)
    speed = 1001.0 / 1000.0
    points = [
        MatchPoint(t, t * speed + 0.125, 0.99, 99.0)
        for t in (10.0, 120.5, 333.25, 600.75, 900.0)
    ]

    mapping = classify_time_mapping(points, source_info=source, target_info=target, expected_count=len(points))

    assert mapping.mode == "B"
    assert mapping.speed_factor == pytest.approx(speed, rel=1e-6)
    assert mapping.offset_s == pytest.approx(0.125, abs=1e-6)


def test_short_clip_landmark_selection_stays_inside_clip_bounds():
    from dragontools.core.audio_video_time_mapping import select_landmark_times

    assert select_landmark_times(1.0) == [pytest.approx(0.5)]
    assert select_landmark_times(0.2) == [pytest.approx(0.1)]


def test_real_vfr_clip_can_be_sampled_by_timestamp(tmp_path):
    import json
    import shutil
    import subprocess

    from dragontools.core.audio_video_frame_analysis import FrameExtractor
    from dragontools.core.audio_video_match_models import AudioVideoMatcherSettings

    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg/ffprobe für synthetischen VFR-Test nicht verfügbar")

    clip = tmp_path / "vfr.mkv"
    completed = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x90:rate=24000/1001:duration=1.5",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x90:rate=30000/1001:duration=1.5",
            "-filter_complex",
            "[0:v]setpts=PTS-STARTPTS[v0];[1:v]setpts=PTS-STARTPTS[v1];[v0][v1]concat=n=2:v=1:a=0[v]",
            "-map",
            "[v]",
            "-fps_mode",
            "vfr",
            "-c:v",
            "ffv1",
            str(clip),
        ],
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")

    probe = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=avg_frame_rate,r_frame_rate",
            "-of",
            "json",
            str(clip),
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    stream = json.loads(probe.stdout)["streams"][0]
    assert stream["avg_frame_rate"] == "0/0" or stream["avg_frame_rate"] != stream["r_frame_rate"]

    extractor = FrameExtractor(
        ffmpeg,
        settings=AudioVideoMatcherSettings(analysis_width=64, analysis_height=36),
    )
    signatures = extractor.extract_window_signatures(str(clip), 0.25, 2.5, fps=2.5)

    assert len(signatures) == 6
    assert [item.time_s for item in signatures] == pytest.approx(
        [0.25, 0.65, 1.05, 1.45, 1.85, 2.25],
        abs=0.001,
    )
