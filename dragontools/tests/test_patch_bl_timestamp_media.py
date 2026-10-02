"""Real mux tests: the assertions inspect packets/timing, not just argv."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from dragontools.tests.ci_requirements import external_media_environment
from dragontools.worker.audio_mux_plan_service import AudioMuxPlanService
from dragontools.worker.converter_strip_movtext_fallback import run_strip_command
from dragontools.worker.mp4_remux_plan import MP4RemuxPlanner
from dragontools.worker.output_verifier import OutputVerifier
from dragontools.worker.standard_pipeline_runner import StandardPipelineRunner
from dragontools.worker.workflow_models import PipelineExecutionRequest

pytestmark = pytest.mark.media_integration


def run(cmd):
    result = subprocess.run(list(cmd), capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr[-4000:]
    return result


def probe(tools, path):
    return json.loads(run([tools.ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]).stdout)


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    env = external_media_environment()
    if not env.ffmpeg or not env.ffprobe:
        pytest.skip("FFmpeg/ffprobe unavailable")
    tools = NS(ffmpeg=env.ffmpeg, ffprobe=env.ffprobe)
    root = tmp_path_factory.mktemp("timestamp_media")
    src = root / "offset.mp4"
    # The .8s intentional audio delay and reordered video packets exercise
    # shared shifting: video packet DTS is negative even for a clean source.
    run([tools.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i",
         "testsrc2=size=160x90:rate=25:duration=3", "-itsoffset", "0.8", "-f", "lavfi", "-i",
         "sine=frequency=440:sample_rate=48000:duration=2", "-c:v", "libx264", "-preset", "fast",
         "-c:a", "aac", str(src)])
    packets = json.loads(run([tools.ffprobe, "-v", "error", "-select_streams", "v:0",
        "-read_intervals", "%+#4", "-show_packets", "-of", "json", str(src)]).stdout)["packets"]
    assert float(packets[0]["dts_time"]) < 0
    return tools, src


def request(src, out, codec="h264"):
    return PipelineExecutionRequest(pipeline="standard", input_path=str(src), output_path=str(out),
        container=out.suffix[1:], media_info=NS(is_hdr=False, video_streams=[], audio_streams=[], subtitle_streams=[]),
        plan=NS(vf_args=["-map", "0:v:0"], audio_input_args=[], audio_args=["-map", "0:a:0", "-c:a", "copy"], sn=["-sn"]),
        override={}, strip_only=False, duration_ms=3000, codec=codec, crf=24, preset="fast", encoder_options={"encoder": "cpu"})


def assert_good(tools, src, out):
    before, after = probe(tools, src), probe(tools, out)
    def offset(data):
        video = next(s for s in data["streams"] if s["codec_type"] == "video")
        audio = next(s for s in data["streams"] if s["codec_type"] == "audio")
        return float(audio["start_time"]) - float(video["start_time"])
    assert offset(after) == pytest.approx(offset(before), abs=.003)
    assert 2.95 <= float(after["format"]["duration"]) <= 3.15
    result = OutputVerifier(ffprobe_path=tools.ffprobe).verify(str(out), out.suffix[1:], expected_duration_ms=3000, source_has_audio=True)
    assert result.duration_ok and result.video_ok and result.audio_ok
    from dragontools.worker.duration_repair_policy import can_repair_duration
    assert not can_repair_duration(output_path=str(out), container=out.suffix[1:], verify_result=result,
                                  normal_remux_enabled=True, timestamp_repair_enabled=True)


@pytest.mark.parametrize("codec", ["h264", "h265"])
@pytest.mark.parametrize("container", ["mkv", "mp4", "mov"])
def test_real_standard_encode_preserves_offset_without_repair(media, tmp_path, codec, container):
    tools, src = media
    out = tmp_path / f"out.{container}"
    runner = StandardPipelineRunner(tools=tools, codec=codec, crf=24, preset="fast", encoder_options={"encoder": "cpu"},
        progress_runner=lambda cmd, *_: run(cmd).returncode)
    assert runner.execute(request(src, out, codec)).success
    assert_good(tools, src, out)


@pytest.mark.parametrize("container", ["mkv", "mp4"])
def test_real_strip_only_preserves_offset(media, tmp_path, container):
    tools, src = media
    out = tmp_path / f"stripped.{container}"
    worker = NS(tools=tools, _progress=NS(run=lambda cmd: run(cmd).returncode))
    assert run_strip_command(worker, inp=str(src), out=str(out), container=container, audio_input_args=[],
                             audio_args=["-map", "0:a", "-c:a", "copy"], subtitle_args=["-sn"])
    assert_good(tools, src, out)


def test_real_audio_mux_preserves_offset(media, tmp_path):
    tools, src = media
    out = tmp_path / "audio_mux.mkv"
    plan = [NS(stream=NS(index=1), out_idx=0, needs_transcode=False, drc_scale=None)]
    run(AudioMuxPlanService(tools=tools).build_ffmpeg_cmd(str(src), str(out), plan))
    assert_good(tools, src, out)


def test_real_mp4_remux_preserves_offset(media, tmp_path, monkeypatch):
    tools, src = media
    out = tmp_path / "remux.mp4"
    planner = MP4RemuxPlanner(ffmpeg_path=tools.ffmpeg, apply_audio_rules=False, export_subtitles=False,
        ignore_subtitles=True, subtitle_rules={}, faststart=True, log=lambda *_: None, log_audio=lambda *_: None)
    monkeypatch.setattr(planner, "build_audio_plan", lambda _: [])
    monkeypatch.setattr(planner, "build_audio_args", lambda _: ["-map", "0:a", "-c:a", "copy"])
    plan = planner.build(str(src), str(out), NS(duration_s=3))
    run(plan.command)
    assert_good(tools, src, out)


@pytest.mark.parametrize("container", ["mkv", "mp4"])
def test_real_negative_source_start_is_normalized_without_wrap(media, tmp_path, container):
    tools, original = media
    src = tmp_path / "negative.ts"
    run([tools.ffmpeg, "-y", "-v", "error", "-i", str(original), "-map", "0", "-c", "copy",
         "-output_ts_offset", "-0.8", "-avoid_negative_ts", "disabled", "-mpegts_copyts", "1", str(src)])
    source = probe(tools, src)
    assert float(source["streams"][0]["start_time"]) == pytest.approx(-.8)
    assert float(source["streams"][1]["start_time"]) == pytest.approx(0, abs=.03)
    out = tmp_path / f"negative_encoded.{container}"
    runner = StandardPipelineRunner(tools=tools, codec="h265", crf=24, preset="fast", encoder_options={"encoder": "cpu"},
        progress_runner=lambda cmd, *_: run(cmd).returncode)
    assert runner.execute(request(src, out, "h265")).success
    assert_good(tools, src, out)


@pytest.mark.parametrize("comfy", [False, True])
@pytest.mark.parametrize("retry", [False, True])
def test_standard_and_comfy_movtext_retry_use_same_policy(media, tmp_path, monkeypatch, comfy, retry):
    from dataclasses import replace
    from dragontools.worker import standard_pipeline_runner as module
    tools, src = media
    out = tmp_path / "output.mkv"
    commands = []
    def progress(cmd, *_):
        commands.append(cmd)
        return 1 if retry and len(commands) == 1 else 0
    runner = StandardPipelineRunner(tools=tools, codec="h264", crf=24, preset="fast", encoder_options={}, progress_runner=progress)
    monkeypatch.setattr(runner, "_selected_mkv_mov_text_streams", lambda _: [NS(index=2)])
    monkeypatch.setattr(runner, "_export_mov_text_backup", lambda *_: NS(complete=True, exported_paths=[]))
    monkeypatch.setattr(module, "build_subtitle_args", lambda *a, **kw: (None, ["-sn"]))
    monkeypatch.setattr(module.ComfyUIHDRVideoService, "render", lambda *a, **kw: NS(success=True, peak_vram_bytes=0, elapsed_s=0, frames=75))
    req = request(src, out)
    if comfy:
        req = replace(req, encoder_options={"_sdr_hdr_applied": True, "sdr_hdr_backend": "comfyui"})
    assert runner.execute(req).success
    assert len(commands) == (2 if retry else 1)
    for cmd in commands:
        assert cmd.count("-avoid_negative_ts") == 1
        index = cmd.index("-avoid_negative_ts")
        assert cmd[index + 1] == "make_zero"
        assert index > max(i for i, token in enumerate(cmd) if token == "-i")
        assert not any(token in {"-copyts", "-start_at_zero", "+genpts+igndts"} for token in cmd)


def test_real_subtitle_injection_preserves_event_offset(media, tmp_path):
    from dragontools.subtitle.injector import inject_with_ffmpeg
    tools, src = media
    subtitle = tmp_path / "sub.srt"
    subtitle.write_text("1\n00:00:00,600 --> 00:00:01,600\nTiming test\n", encoding="utf-8")
    out = tmp_path / "subtitled.mkv"
    assert inject_with_ffmpeg(str(src), str(subtitle), str(out), ffmpeg=tools.ffmpeg,
                              ffprobe=tools.ffprobe, existing_subtitle_count=0)
    data = probe(tools, out)
    video_start = float(next(s for s in data["streams"] if s["codec_type"] == "video")["start_time"])
    packets = json.loads(run([tools.ffprobe, "-v", "error", "-select_streams", "s:0",
        "-show_packets", "-read_intervals", "%+#1", "-of", "json", str(out)]).stdout)["packets"]
    assert float(packets[0]["pts_time"]) - video_start == pytest.approx(.6, abs=.002)
    assert_good(tools, src, out)
