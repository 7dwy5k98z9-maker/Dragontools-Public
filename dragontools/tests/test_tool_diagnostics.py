from __future__ import annotations


def test_probe_ffmpeg_reports_version_and_features(monkeypatch):
    import dragontools.core.tool_diagnostics as module

    monkeypatch.setattr(module, "_exists_or_which", lambda _path: True)

    def fake_run(path, args, *, timeout=5):
        if "-version" in args:
            return 0, "ffmpeg version 7.1-full"
        if "-filters" in args:
            return 0, " ... libplacebo ...\n ... zscale ...\n ... subtitles ..."
        if "-encoders" in args:
            return 0, " hevc_nvenc\n hevc_qsv\n hevc_amf\n libx265\n libsvtav1"
        if "encoder=hevc_nvenc" in args:
            return 0, "-lookahead_level <int>\n-multipass <int>"
        return 0, ""

    monkeypatch.setattr(module, "_run_tool", fake_run)

    info = module.probe_tool("ffmpeg", "ffmpeg.exe")

    assert info["found"] is True
    assert info["version"] == "ffmpeg version 7.1-full"
    assert "libplacebo" in info["features"]
    assert "zscale" in info["features"]
    assert "NVENC" in info["features"]
    assert "NVENC lookahead_level" in info["features"]
    assert "NVENC multipass" in info["features"]
    assert "SVT-AV1" in info["features"]


def test_format_tool_diagnostics_marks_missing_tool():
    from dragontools.core.tool_diagnostics import format_tool_diagnostics

    text = format_tool_diagnostics([
        {"name": "dovi_tool", "found": False, "path": "dovi_tool.exe"}
    ])

    assert "❌" in text
    assert "dovi_tool" in text
    assert "nicht gefunden" in text


def test_handbrake_gui_is_not_started_for_version_probe(monkeypatch):
    import dragontools.core.tool_diagnostics as module

    calls = []
    monkeypatch.setattr(module, "_exists_or_which", lambda _path: True)

    def fake_run(path, args, *, timeout=5):
        calls.append(args)
        return 0, ""

    monkeypatch.setattr(module, "_run_tool", fake_run)

    info = module.probe_tool("handbrake", r"C:\Tools\HandBrake.exe")

    assert info["found"] is True
    assert calls == [[]]


def test_extended_system_test_runs_mini_tool_chain(monkeypatch):
    import dragontools.core.tool_diagnostics as module

    monkeypatch.setattr(module, "_exists_or_which", lambda _path: True)
    commands = []

    def fake_runner(cmd, timeout):
        commands.append(cmd)
        out = cmd[cmd.index("-o") + 1] if "-o" in cmd else cmd[-1]
        if str(out).endswith((".avi", ".mkv", ".mp4")):
            from pathlib import Path

            Path(out).write_bytes(b"mini")
        if "-show_entries" in cmd:
            return 0, "1.000000"
        if "--Output=JSON" in cmd:
            return 0, '{"media":{"track":[]}}'
        return 0, "tool ok"

    rows = module.run_extended_system_test(
        {
            "ffmpeg": "ffmpeg.exe",
            "ffprobe": "ffprobe.exe",
            "mediainfo": "MediaInfo.exe",
            "mkvmerge": "mkvmerge.exe",
            "mp4box": "mp4box.exe",
            "dovi_tool": "dovi_tool.exe",
            "hdr10plus_tool": "hdr10plus_tool.exe",
        },
        runner=fake_runner,
    )

    assert all(row["ok"] for row in rows)
    assert any("testsrc=size=64x64" in " ".join(cmd) for cmd in commands)
    text = module.format_extended_system_test(rows)
    assert "Erweiterter Systemtest" in text
    assert "✅" in text
