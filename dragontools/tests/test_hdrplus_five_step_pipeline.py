from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace


def _helper(logs=None):
    from dragontools.worker.dv_runtime_models import DVTempState
    from dragontools.worker.hdrplus_conversion import HDRPlusConversionHelper

    logs = logs if logs is not None else []
    tools = SimpleNamespace(
        ffmpeg="ffmpeg",
        ffprobe="ffprobe",
        hdr10plus_tool="hdr10plus_tool",
        mkvmerge="mkvmerge",
        mp4box="MP4Box",
    )
    progress = SimpleNamespace(worker=None, probe_ms=lambda *_: 100_000, run_p=None)
    helper = HDRPlusConversionHelper(
        tools=tools,
        log=lambda msg, level="info": logs.append((level, msg)),
        codec="h265",
        crf=22,
        preset="medium",
        encoder_options={"encoder": "cpu"},
        progress_runner=progress,
        temp_state=DVTempState(),
    )
    return helper, logs


def test_hdrplus_mkv_uses_direct_flow_and_annexb_only_as_extract_fallback(tmp_path, monkeypatch):
    helper, logs = _helper()
    source = tmp_path / "source.mkv"
    output = tmp_path / "output.mkv"
    source.write_bytes(b"s" * 2048)
    media = SimpleNamespace(
        primary_video=SimpleNamespace(
            codec="hevc", hdr_format="hdr10plus", color_transfer="PQ", color_primaries="BT.2020"
        ),
        has_hdr10plus=True,
        audio_streams=[],
        subtitle_streams=[],
    )
    seen = {"extract_sources": [], "encode_cmd": None, "mux_donor": None}

    def fake_meta(src, dst):
        seen["extract_sources"].append(Path(src))
        Path(dst).write_text(json.dumps({"SceneInfo": [1]}), encoding="utf-8")
        return True

    def fake_encode(cmd, _input, _duration):
        seen["encode_cmd"] = list(cmd)
        idx = cmd.index("-f")
        assert cmd[idx + 1] == "hevc"
        Path(cmd[idx + 2]).write_bytes(b"e" * 2048)
        return 0

    def fake_inject(_encoded, _meta, dst):
        Path(dst).write_bytes(b"i" * 2048)
        return True

    def fake_mux(injected, donor, dst, *, container, tmp_dir=None):
        assert container == "mkv"
        assert Path(injected).name == "injected.hevc"
        seen["mux_donor"] = donor
        Path(dst).write_bytes(b"o" * 2048)
        return True

    helper._progress.run_p = fake_encode
    monkeypatch.setattr(helper, "_extract_hdr10plus_metadata", fake_meta)
    monkeypatch.setattr(helper, "_inject_hdr10plus_metadata", fake_inject)
    monkeypatch.setattr(helper, "_mux_hdrplus_output", fake_mux)
    monkeypatch.setattr(helper, "_verify_final_hdr10plus", lambda *_: True)
    monkeypatch.setattr(
        helper,
        "_extract_hevc_annexb",
        lambda *_: (_ for _ in ()).throw(AssertionError("MKV darf keinen source.hevc-Fallback benötigen")),
    )

    assert helper.run(
        str(source), str(output), media,
        vf_args=["-map", "0:v:0"], audio_args=["-an"], audio_input_args=[], sn=["-sn"], crop=None,
    ) is True

    assert seen["extract_sources"] == [source]
    cmd_text = " ".join(seen["encode_cmd"])
    assert "encoded.mkv" not in cmd_text
    assert "source.hevc" not in cmd_text
    assert "encoded.hevc" in cmd_text
    assert seen["mux_donor"] == ""
    joined = "\n".join(msg for _level, msg in logs)
    for step in range(1, 6):
        assert f"Schritt {step}/5" in joined
    assert "/6" not in joined

    # Regression: schlägt der direkte Matroska-Extract fehl (z. B.
    # hdr10plus_tool: "Invalid PPS index"), muss Schritt 1 automatisch über
    # einen von FFmpeg extrahierten HEVC-Annex-B-Bitstream wiederholt werden.
    fallback_logs = []
    fallback_helper, _ = _helper(fallback_logs)
    fallback_output = tmp_path / "fallback_output.mkv"
    fallback_seen = {"extract_sources": [], "annexb": []}

    def fallback_meta(src, dst):
        src_path = Path(src)
        fallback_seen["extract_sources"].append(src_path)
        if src_path == source:
            return False
        assert src_path.name == "source_metadata.hevc"
        Path(dst).write_text(json.dumps({"SceneInfo": [1]}), encoding="utf-8")
        return True

    def fallback_annexb(src, dst):
        fallback_seen["annexb"].append((Path(src), Path(dst)))
        Path(dst).write_bytes(b"h" * 2048)
        return True

    def fallback_encode(cmd, _input, _duration):
        hevc_idx = cmd.index("hevc")
        Path(cmd[hevc_idx + 1]).write_bytes(b"e" * 2048)
        return 0

    def fallback_inject(_encoded, _meta, dst):
        Path(dst).write_bytes(b"i" * 2048)
        return True

    def fallback_mux(_injected, _donor, dst, *, container, tmp_dir=None):
        assert container == "mkv"
        Path(dst).write_bytes(b"o" * 2048)
        return True

    fallback_helper._progress.run_p = fallback_encode
    monkeypatch.setattr(fallback_helper, "_extract_hdr10plus_metadata", fallback_meta)
    monkeypatch.setattr(fallback_helper, "_extract_hevc_annexb", fallback_annexb)
    monkeypatch.setattr(fallback_helper, "_inject_hdr10plus_metadata", fallback_inject)
    monkeypatch.setattr(fallback_helper, "_mux_hdrplus_output", fallback_mux)
    monkeypatch.setattr(fallback_helper, "_verify_final_hdr10plus", lambda *_: True)

    assert fallback_helper.run(
        str(source), str(fallback_output), media,
        vf_args=["-map", "0:v:0"], audio_args=["-an"], audio_input_args=[], sn=["-sn"], crop=None,
    ) is True

    assert fallback_seen["extract_sources"] == [source, fallback_seen["annexb"][0][1]]
    assert fallback_seen["annexb"][0][0] == source
    assert fallback_seen["annexb"][0][1].name == "source_metadata.hevc"
    fallback_joined = "\n".join(msg for _level, msg in fallback_logs)
    assert "erneuter Versuch über HEVC-Annex-B" in fallback_joined
    assert "Metadata-Extract über HEVC-Annex-B-Fallback erfolgreich" in fallback_joined


def test_hdrplus_encode_builds_stream_donor_in_same_ffmpeg_run(tmp_path):
    helper, _ = _helper()
    source = tmp_path / "source.mkv"
    source.write_bytes(b"s" * 2048)
    encoded = tmp_path / "encoded.hevc"
    donor = tmp_path / "streams.mkv"
    media = SimpleNamespace(
        primary_video=SimpleNamespace(hdr_format="hdr10plus", color_transfer="PQ", color_primaries="BT.2020"),
        has_hdr10plus=True,
    )
    seen = {}

    def fake_encode(cmd, _input, _duration):
        seen["cmd"] = list(cmd)
        hevc_idx = cmd.index("hevc")
        Path(cmd[hevc_idx + 1]).write_bytes(b"v" * 2048)
        Path(cmd[-1]).write_bytes(b"a" * 1024)
        return 0

    helper._progress.run_p = fake_encode
    ok = helper._encode_hevc_and_stream_donor(
        input_path=str(source),
        encoded_hevc=encoded,
        stream_donor=donor,
        vf_args=["-map", "0:v:0"],
        audio_args=["-map", "0:1", "-c:a:0", "copy"],
        audio_input_args=[],
        subtitle_args=["-sn"],
        media_info=media,
    )
    assert ok is True
    assert encoded.exists() and donor.exists()
    cmd = seen["cmd"]
    assert cmd.count(str(source)) == 1
    assert str(encoded) in cmd and str(donor) in cmd
    assert cmd.index(str(encoded)) < cmd.index("-map", cmd.index(str(encoded)) + 1)
    assert "-map_chapters" in cmd


def test_hdrplus_mkv_mux_uses_mkvmerge_not_ffmpeg(tmp_path, monkeypatch):
    helper, _ = _helper()
    injected = tmp_path / "injected.hevc"
    donor = tmp_path / "streams.mkv"
    output = tmp_path / "final.mkv"
    injected.write_bytes(b"v" * 2048)
    donor.write_bytes(b"a" * 1024)
    seen = {}

    class Result:
        ok = True
        returncode = 0
        stdout = ""
        stderr = ""
        def tail(self, *_):
            return ""

    def fake_run(cmd, **kwargs):
        seen["cmd"] = list(cmd)
        output.write_bytes(b"o" * 4096)
        return Result()

    monkeypatch.setattr("dragontools.worker.hdrplus_conversion.run_tool", fake_run)
    assert helper._mux_hdrplus_mkv(str(injected), str(donor), str(output)) is True
    assert seen["cmd"][0] == "mkvmerge"
    assert "ffmpeg" not in seen["cmd"]
    assert "--no-video" in seen["cmd"]
    assert str(injected) in seen["cmd"] and str(donor) in seen["cmd"]


def test_hdrplus_mp4_mux_is_streaming_optimized_with_mp4box(tmp_path, monkeypatch):
    helper, _ = _helper()
    injected = tmp_path / "injected.hevc"
    output = tmp_path / "final.mp4"
    injected.write_bytes(b"v" * 2048)
    seen = {}

    class Result:
        ok = True
        returncode = 0
        stdout = ""
        stderr = ""
        def tail(self, *_):
            return ""

    def fake_run(cmd, **kwargs):
        seen["cmd"] = list(cmd)
        output.write_bytes(b"o" * 4096)
        return Result()

    monkeypatch.setattr("dragontools.worker.hdrplus_conversion.run_tool", fake_run)
    assert helper._mux_hdrplus_mp4(str(injected), "", str(output), tmp_dir=tmp_path) is True
    assert seen["cmd"][0] == "MP4Box"
    assert "-inter" in seen["cmd"]
    assert seen["cmd"][seen["cmd"].index("-inter") + 1] == "500"
    assert "-add" in seen["cmd"] and str(injected) in seen["cmd"]


def test_hdrplus_mp4_mux_aborts_instead_of_silently_dropping_audio_on_probe_failure(tmp_path, monkeypatch):
    from dragontools.worker.tool_runner import ToolRunResult

    helper, logs = _helper()
    injected = tmp_path / "injected.hevc"
    donor = tmp_path / "streams.mkv"
    output = tmp_path / "final.mp4"
    injected.write_bytes(b"v" * 2048)
    donor.write_bytes(b"a" * 1024)

    def fake_run(cmd, **_kwargs):
        command = list(cmd)
        if command and command[0] == "ffprobe":
            return ToolRunResult(command=command, returncode=1, stderr="probe failed")
        raise AssertionError("MP4Box darf nach fehlgeschlagener Audioanalyse nicht gestartet werden")

    monkeypatch.setattr("dragontools.worker.hdrplus_conversion.run_tool", fake_run)

    assert helper._mux_hdrplus_mp4(
        str(injected), str(donor), str(output), tmp_dir=tmp_path
    ) is False
    assert not output.exists()
    assert any("Audio" in message and level == "error" for level, message in logs)
