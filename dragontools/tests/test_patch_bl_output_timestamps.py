from __future__ import annotations

import json
from types import SimpleNamespace as NS

import pytest

from dragontools.core.media_duration import source_duration, timestamp_wrap, TIMESTAMP_WRAP_SECONDS
from dragontools.core.output_timestamps import build_output_timestamp_args
from dragontools.worker.output_verifier import OutputVerifier
from dragontools.worker.timestamp_diagnostics import log_timestamp_diagnostics


def payload(video=2400, container=2400, audio=2410, subtitle=9000):
    return {"format": {"duration": container}, "streams": [
        {"index": 0, "codec_type": "video", "duration": video, "start_time": -.8},
        {"index": 1, "codec_type": "audio", "duration": audio, "start_time": 0},
        {"index": 2, "codec_type": "subtitle", "duration": subtitle},
        {"index": 3, "codec_type": "data", "duration": 1e9},
    ]}


@pytest.mark.parametrize("data,expected", [
    (payload(), 2400), (payload(container=None), 2400),
    (payload(video=None), 2400), (payload(video=None, container=None), 2410),
    (payload(video=None, container=None, audio=None), None),
    (payload(video=4297505.5, container=2539, audio=2539), 2539),
    (payload(container=4297505.5), 2400),
    (payload(video=9000, container=2400, audio=2400), 2400),
    (payload(video=2400, container=9000, audio=2410), 2400),
])
def test_source_duration_priorities(data, expected):
    assert source_duration(data) == expected


@pytest.mark.parametrize("invalid", [None, "N/A", "nan", "inf", "-inf", 0, -1, "bad"])
def test_invalid_video_duration_falls_back(invalid):
    assert source_duration(payload(video=invalid)) == 2400


def test_mkv_endpoint_tag_and_multiple_video_streams():
    data = payload(video=None)
    data["streams"][0].update(start_time=.8, tags={"DURATION": "00:40:00.800000000"})
    data["streams"].append({"codec_type": "video", "duration": 8000})
    assert source_duration(data) == 2400


def test_cover_art_is_not_duration_reference():
    data = payload()
    data["streams"].insert(0, {"codec_type": "video", "duration": 1, "disposition": {"attached_pic": 1}})
    assert source_duration(data) == 2400


def test_vfr_does_not_invent_duration_from_fps():
    data = payload(video=None)
    data["streams"][0].update(avg_frame_rate="25/1", r_frame_rate="50/1", nb_frames=900000)
    assert source_duration(data) == 2400


def test_wrap_and_normal_output_remain_distinct():
    assert timestamp_wrap(2539, 4297505.5) == pytest.approx((1, -.796))
    assert timestamp_wrap(2539, 2539 + 2 * TIMESTAMP_WRAP_SECONDS + .1) == pytest.approx((2, .1))
    for actual in (2539, 2540, 5000, 4290000):
        assert timestamp_wrap(2539, actual) is None
    verifier = OutputVerifier(ffprobe_path="unused")
    assert verifier._duration_plausible(2539.08, expected_duration_ms=2539000)
    assert not verifier._duration_plausible(4297505.5, expected_duration_ms=2539000)


@pytest.mark.parametrize("container", ["mkv", "MP4", ".mov", "file.m4v", "matroska"])
def test_final_output_policy(container):
    assert build_output_timestamp_args(container) == ["-avoid_negative_ts", "make_zero"]


@pytest.mark.parametrize("role", ["donor", "elementary", "repair"])
def test_separate_timelines_are_not_independently_zeroed(role):
    assert build_output_timestamp_args("mkv", role=role) == []
    assert build_output_timestamp_args("raw.hevc") == []


def test_converter_probe_uses_video_not_long_subtitle(monkeypatch):
    from dragontools.worker.converter_media_probe import probe_ms
    calls = []
    def run(cmd, **kwargs):
        calls.append(cmd)
        return NS(returncode=0, stdout=json.dumps(payload()), stderr="")
    monkeypatch.setattr("dragontools.worker.converter_media_probe.subprocess.run", run)
    worker = NS(tools=NS(ffprobe="ffprobe"), log=lambda *_: None)
    assert probe_ms(worker, "source.mkv") == 2400000
    assert "-count_frames" not in calls[0]


def test_diagnostics_are_bounded_and_log_wrap_stream(monkeypatch):
    calls, logs = [], []
    def run(cmd, **kwargs):
        calls.append(cmd)
        data = payload(video=4297505.5, container=4297505.5)
        if "-show_packets" in cmd:
            data = {"packets": [{"pts_time": "-0.8", "dts_time": "-0.88"}]}
        return NS(returncode=0, stdout=json.dumps(data), stderr="")
    monkeypatch.setattr("dragontools.worker.timestamp_diagnostics.subprocess.run", run)
    log_timestamp_diagnostics(source_path="source", output_path="out", expected_s=2539,
        actual_s=4297505.5, container="mkv", ffprobe_path="ffprobe", log=lambda msg, level: logs.append(msg))
    text = "\n".join(logs)
    for token in ("Quelle", "Ausgabe", "start_time=-0.8", "time_base", "avg_frame_rate", "r_frame_rate",
                  "Wrap-Anzahl=1", "Restabweichung=-0.796", "video #0", "PTS/DTS"):
        assert token in text
    assert len(calls) == 4
    assert all("-count_frames" not in cmd for cmd in calls)
    assert all("%+#16" in cmd for cmd in calls if "-show_packets" in cmd)


def test_diagnostic_failure_does_not_block_repair(monkeypatch):
    def broken(*args, **kwargs):
        raise TimeoutError("test")
    monkeypatch.setattr("dragontools.worker.timestamp_diagnostics.subprocess.run", broken)
    logs = []
    log_timestamp_diagnostics(source_path="src", output_path="out", expected_s=1,
        actual_s=2, container="mkv", ffprobe_path="ffprobe", log=lambda m, l: logs.append(m))
    assert len(logs) == 2


def test_diagnostics_run_before_any_repair_mutation(monkeypatch, tmp_path):
    from dragontools.worker.duration_repair_service import DurationRepairService
    from dragontools.worker.workflow_engine import WorkflowVerifyResult
    events = []
    service = DurationRepairService(mkvmerge_path="mkvmerge", ffprobe_path="ffprobe",
        output_verifier=NS(), log=lambda *_: None)
    monkeypatch.setattr(service, "can_repair", lambda **kw: True)
    monkeypatch.setattr("dragontools.worker.duration_repair_service.log_timestamp_diagnostics",
                        lambda **kw: events.append("diagnostic"))
    monkeypatch.setattr(service._orchestrator, "repair", lambda **kw: events.append("repair"))
    service.repair(output_path=str(tmp_path / "out.mkv"), source_path="source.mkv", base_dir=tmp_path,
        container="mkv", expected_duration_ms=2539000, source_has_audio=True,
        initial_result=WorkflowVerifyResult(duration_s=4297505.5))
    assert events == ["diagnostic", "repair"]


def test_avmatch_does_not_hide_broken_container_behind_video_reference(monkeypatch, tmp_path):
    from dragontools.worker import audio_video_match_render as module
    path = tmp_path / "out.mkv"
    path.write_bytes(b"output")
    monkeypatch.setattr(module, "analyze_media", lambda *a: NS(duration_s=2539))
    monkeypatch.setattr(module, "probe_output", lambda *a, **kw: NS(duration_s=4297505.5))
    with pytest.raises(RuntimeError, match="unplausibel"):
        module.validate_output(path, NS(ffprobe="ffprobe"), target_duration_s=2539)


def test_mediainfo_fallback_matches_selected_video_index():
    data = payload(video=None, container=None)
    assert source_duration(data, video_streams=[NS(index=0, duration_s=2399), NS(index=4, duration_s=9000)]) == 2399


def test_output_verifier_still_rejects_wrap_with_healthy_video(monkeypatch, tmp_path):
    from dragontools.worker.output_probe import OutputProbeData
    path = tmp_path / "out.mkv"
    path.write_bytes(b"0" * 2048)
    monkeypatch.setattr("dragontools.worker.output_verifier.probe_output", lambda *a, **kw:
        OutputProbeData("matroska", 4297505.5, ({"codec_type": "video", "duration": "2539"},)))
    result = OutputVerifier(ffprobe_path="ffprobe").verify(str(path), "mkv", expected_duration_ms=2539000)
    assert not result.duration_ok
    assert any("Timestamp-Wrap" in message for message in result.messages)
