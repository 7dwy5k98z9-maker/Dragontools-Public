from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace


def _ok_result(*, stdout: str = "") -> SimpleNamespace:
    return SimpleNamespace(ok=True, returncode=0, stdout=stdout, stderr="")


def test_mp4_injection_sets_language_and_forced_on_new_subtitle_without_probe(monkeypatch, tmp_path):
    import dragontools.subtitle.injector as module

    out = tmp_path / "film_sub.mp4"
    calls: list[list[str]] = []

    def fake_run_tool(cmd, **kwargs):
        calls.append(cmd)
        out.write_bytes(b"video")
        return _ok_result()

    monkeypatch.setattr(module, "run_tool", fake_run_tool)

    assert module.inject_with_ffmpeg(
        "film.mp4",
        "film.de.srt",
        str(out),
        language="deu",
        subtitle_codec="mov_text",
        map_existing_subtitles=False,
        forced=True,
        ffmpeg="C:/Tools/ffmpeg.exe",
        ffprobe="C:/Tools/ffprobe.exe",
    )

    assert len(calls) == 1
    cmd = calls[0]
    assert "-metadata:s:s:0" in cmd
    assert cmd[cmd.index("-metadata:s:s:0") + 1] == "language=deu"
    assert "-disposition:s:0" in cmd
    assert cmd[cmd.index("-disposition:s:0") + 1] == "forced"


def test_mkv_ffmpeg_fallback_targets_appended_subtitle_after_existing_tracks(monkeypatch, tmp_path):
    import dragontools.subtitle.injector as module

    out = tmp_path / "film_sub.mkv"
    calls: list[list[str]] = []

    def fake_run_tool(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0].endswith("ffprobe.exe"):
            return _ok_result(stdout=json.dumps({"streams": [{"index": 4}, {"index": 7}]}))
        out.write_bytes(b"video")
        return _ok_result()

    monkeypatch.setattr(module, "run_tool", fake_run_tool)

    assert module.inject_with_ffmpeg(
        "film.mkv",
        "film.de.srt",
        str(out),
        language="deu",
        forced=True,
        ffmpeg="C:/Tools/ffmpeg.exe",
        ffprobe="C:/Tools/ffprobe.exe",
    )

    assert len(calls) == 2
    probe_cmd, ffmpeg_cmd = calls
    assert probe_cmd[0] == "C:/Tools/ffprobe.exe"
    assert "-select_streams" in probe_cmd
    assert probe_cmd[probe_cmd.index("-select_streams") + 1] == "s"
    assert "-metadata:s:s:2" in ffmpeg_cmd
    assert ffmpeg_cmd[ffmpeg_cmd.index("-metadata:s:s:2") + 1] == "language=deu"
    assert "-disposition:s:2" in ffmpeg_cmd
    assert ffmpeg_cmd[ffmpeg_cmd.index("-disposition:s:2") + 1] == "forced"
    assert "-metadata:s:s:0" not in ffmpeg_cmd


def test_ffmpeg_injection_explicitly_clears_forced_on_new_track(monkeypatch, tmp_path):
    import dragontools.subtitle.injector as module

    out = tmp_path / "film_sub.mkv"
    seen: dict[str, list[str]] = {}

    def fake_run_tool(cmd, **kwargs):
        seen["cmd"] = cmd
        out.write_bytes(b"video")
        return _ok_result()

    monkeypatch.setattr(module, "run_tool", fake_run_tool)

    assert module.inject_with_ffmpeg(
        "film.mkv",
        "film.en.srt",
        str(out),
        language="eng",
        forced=False,
        existing_subtitle_count=3,
    )

    cmd = seen["cmd"]
    assert "-metadata:s:s:3" in cmd
    assert cmd[cmd.index("-metadata:s:s:3") + 1] == "language=eng"
    assert cmd[cmd.index("-disposition:s:3") + 1] == "0"


def test_ffmpeg_injection_fails_closed_when_existing_subtitle_count_cannot_be_probed(monkeypatch, tmp_path):
    import dragontools.subtitle.injector as module

    out = tmp_path / "film_sub.mkv"
    calls: list[list[str]] = []
    logs: list[str] = []

    def fake_run_tool(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(ok=False, returncode=1, stdout="", stderr="probe failed")

    monkeypatch.setattr(module, "run_tool", fake_run_tool)

    assert module.inject_with_ffmpeg(
        "film.mkv",
        "film.de.srt",
        str(out),
        ffmpeg="C:/Tools/ffmpeg.exe",
        ffprobe="C:/Tools/ffprobe.exe",
        logger=logs.append,
    ) is False

    assert len(calls) == 1
    assert calls[0][0] == "C:/Tools/ffprobe.exe"
    assert not out.exists()
    assert any("nicht sicher bestimmbar" in message for message in logs)


def test_ffprobe_path_is_derived_from_configured_ffmpeg_when_not_explicit():
    import dragontools.subtitle.injector as module

    assert module._ffprobe_for_ffmpeg("C:/Tools/ffmpeg.exe", None) == str(Path("C:/Tools/ffprobe.exe"))
    assert module._ffprobe_for_ffmpeg("ffmpeg", None) == "ffprobe"
