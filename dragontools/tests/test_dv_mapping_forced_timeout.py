from types import SimpleNamespace

import pytest

from dragontools.worker.dv_encode_command import build_dv_encode_command
from dragontools.worker.dv_video_filters import build_dv5_libplacebo_vf
from dragontools.worker.dv_runtime_models import DVEncoderConfig
from dragontools.worker.dv_mp4box_muxer import DVMP4BoxMuxer
from dragontools.worker.dv_command_runner import DVCommandRunner


@pytest.mark.parametrize("vf", [[], ["-map", "0:v:0"], ["-map", "0:v:0", "-vf", "crop=1280:720:0:0"]])
def test_p5_simple_encode_explicitly_selects_first_video(tmp_path, vf):
    plan = build_dv_encode_command(
        ffmpeg_path="ffmpeg", encoder_config=DVEncoderConfig("h265", 22, "medium", {"encoder": "cpu"}),
        input_path="two_video_tracks.mkv", output_hevc=tmp_path / "out.hevc", vf_args=vf, profile_major=5,
    )
    cmd = plan.command
    assert cmd[cmd.index("-map") + 1] == "0:v:0"
    assert cmd.count("-map") == 1
    assert "libplacebo=" in cmd[cmd.index("-vf") + 1]


def test_p5_complex_burn_maps_only_filtered_output():
    vf = ["-map", "0:v:0", "-filter_complex", "[0:v:0][0:s:0]overlay[vout]", "-map", "[vout]"]
    result = build_dv5_libplacebo_vf(vf)
    assert [result[i+1] for i, value in enumerate(result) if value == "-map"] == ["[vout]"]
    assert result[result.index("-filter_complex")+1].startswith("[0:v:0]libplacebo=")


@pytest.mark.parametrize("forced", [True, False])
def test_mp4_forced_subtitle_uses_technical_flags(tmp_path, forced):
    subtitle = tmp_path / "sub.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nHallo\n")
    track = SimpleNamespace(path=subtitle, language="deu", title="Deutsch", forced=forced)
    commands = []
    mux = DVMP4BoxMuxer(mp4box_path="MP4Box", audio_track_name=lambda _: "")
    assert mux.mux_final_output(lambda cmd: commands.append(cmd) or 0, output_path="out.mp4",
                                injected_hevc="video.hevc", mux_tracks=[], subtitle_tracks=[track])
    command = commands[0]
    arg = [command[i+1] for i, value in enumerate(command) if value == '-add'][-1]
    assert (":hdlr=text:txtflags=0xC0000000" in arg) is forced
    assert ('-kind' in command) is forced
    if forced:
        assert command[command.index('-kind')+1] == '2=urn:mpeg:dash:role:2011=forced-subtitle'


def test_adapter_preserves_defaults_and_honors_command_overrides():
    runner = DVCommandRunner(log=lambda *_: None, verbose_log=lambda *_: None, no_window_kwargs=lambda: {})
    calls = []
    runner.run = lambda cmd, **kwargs: calls.append((cmd, kwargs)) or 0
    run = runner.adapter(timeout=3600, label="Audio-Extraktion", default_return_process=True)
    run(["ffmpeg"])
    run(["ffprobe"], timeout=30, label="ffprobe-Audioanalyse", return_process=False, allow_error=True)
    assert calls[0][1] == dict(timeout=3600, label="Audio-Extraktion", return_process=True, allow_error=False)
    assert calls[1][1] == dict(timeout=30, label="ffprobe-Audioanalyse", return_process=False, allow_error=True)
