from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
import wave

import pytest

from dragontools.worker.dv_remux_pipeline import DVRemuxPipelineRunner
from dragontools.worker.dv_remux_process import DVRemuxProcessRunner


def pipeline(channels, codec, run_cmd, *, ffmpeg="ffmpeg"):
    stream = SimpleNamespace(index=0, language="deu", codec="pcm_s16le", channels=6)
    decision = SimpleNamespace(stream=stream, target_codec=codec, target_channels=channels,
                               target_bitrate=640000 if channels == 6 else 128000,
                               needs_transcode=True, drc_scale=None)
    worker = SimpleNamespace(container="mkv", tools=SimpleNamespace(ffmpeg=ffmpeg), log=lambda *_: None)
    runner = DVRemuxPipelineRunner(
        worker, SimpleNamespace(run_cmd=run_cmd), audio_plan_builder=lambda **_: [decision],
        audio_title_builder=lambda **_: "Deutsch", audio_filter_builder=lambda _: None,
    )
    jobs = runner.build_audio_jobs(SimpleNamespace(audio_streams=[stream]), None)
    return runner, jobs[0]


@pytest.mark.parametrize("channels,codec", [(1, "aac"), (2, "aac"), (6, "eac3")])
def test_audio_plan_drives_target_channels_in_command(tmp_path, channels, codec):
    calls = []
    output = tmp_path / "audio.mka"
    def run_cmd(command, *args, **kwargs):
        calls.append(command)
        output.write_bytes(b"audio")
        return 0
    runner, job = pipeline(channels, codec, run_cmd)
    assert runner.extract_audio("source.mkv", job, str(output), 1000)
    cmd = calls[0]
    assert cmd[cmd.index("-ac") + 1] == str(channels)
    assert cmd[cmd.index("-c:a") + 1] == codec


@pytest.mark.parametrize("channels,codec", [(1, "aac"), (2, "aac"), (6, "eac3")])
def test_real_ffmpeg_audio_job_produces_expected_track(tmp_path, channels, codec):
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg/FFprobe unavailable")
    source, output = tmp_path / "audio.wav", tmp_path / "audio.mka"
    with wave.open(str(source), "wb") as wav:
        wav.setnchannels(6)
        wav.setsampwidth(2)
        wav.setframerate(48000)
        wav.writeframes(b"\0" * (4800 * 6 * 2))
    def run_cmd(cmd, *args, **kwargs):
        result = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        return result.returncode
    runner, job = pipeline(channels, codec, run_cmd, ffmpeg=ffmpeg)
    assert runner.extract_audio(str(source), job, str(output), 100)
    probe = subprocess.run([ffprobe, "-v", "error", "-show_entries", "stream=codec_name,channels",
                            "-of", "json", str(output)], capture_output=True, text=True, timeout=30, check=True)
    stream = json.loads(probe.stdout)["streams"][0]
    assert stream["codec_name"] == codec and stream["channels"] == channels


@pytest.mark.parametrize("pct_range", [(0, 55), (55, 80), (80, 82)])
def test_eta_tracks_entire_media_not_gui_phase(monkeypatch, pct_range):
    monkeypatch.setattr("dragontools.worker.dv_remux_process.time.time", lambda: 110.0)
    # Ten seconds elapsed, 50 of 100 media seconds processed => ten remain.
    for speed in (5.0, None):
        assert DVRemuxProcessRunner._estimate_eta(
            start=100.0, last_out_ms=50000, last_speed=speed, dur_ms=100000, pct_range=pct_range,
        ) == 10.0
