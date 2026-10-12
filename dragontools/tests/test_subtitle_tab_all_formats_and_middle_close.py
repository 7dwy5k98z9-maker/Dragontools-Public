from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_format_registry_handles_webvtt_pgs_and_unknown_without_rejecting():
    from dragontools.subtitle.formats import subtitle_extraction_targets

    webvtt = subtitle_extraction_targets("webvtt", "wvtt")
    assert webvtt[0].suffix == ".vtt"
    assert "webvtt" in webvtt[0].codec_args

    pgs = subtitle_extraction_targets("hdmv_pgs_subtitle")
    assert pgs[0].suffix == ".sup"
    assert "copy" in pgs[0].codec_args

    unknown = subtitle_extraction_targets("brand_new_subtitle_codec")
    assert unknown
    assert unknown[0].suffix == ".mks"
    assert "copy" in unknown[0].codec_args


def test_sidecar_matcher_accepts_vtt_mks_and_uses_idx_for_vobsub_pair(tmp_path):
    from dragontools.subtitle.sidecar_matcher import find_injection_subtitle

    video = tmp_path / "Serie.S01E01.mkv"
    video.write_bytes(b"")
    vtt = tmp_path / "Serie.S01E01.de.vtt"
    vtt.write_text("WEBVTT\n", encoding="utf-8")
    assert find_injection_subtitle(video).name == vtt.name

    vtt.unlink()
    mks = tmp_path / "Serie.S01E01.de.mks"
    mks.write_bytes(b"mks")
    assert find_injection_subtitle(video).name == mks.name

    mks.unlink()
    idx = tmp_path / "Serie.S01E01.de.idx"
    sub = tmp_path / "Serie.S01E01.de.sub"
    idx.write_text("# VobSub index file", encoding="utf-8")
    sub.write_bytes(b"sub")
    assert find_injection_subtitle(video).name == idx.name



def test_mkvmerge_fallback_maps_global_ffprobe_index_to_mkv_track_id(monkeypatch, tmp_path):
    from dragontools.subtitle import extractor

    source = tmp_path / "source.mkv"
    source.write_bytes(b"source")
    output = tmp_path / "track.mks"
    calls = []

    def fake_run_tool(cmd, **_kwargs):
        calls.append(cmd)
        if cmd[0] == "ffprobe":
            return SimpleNamespace(returncode=0, stdout=json.dumps({"streams": [{"index": 3}, {"index": 7}]}), aborted=False, timed_out=False)
        if cmd[:2] == ["mkvmerge", "-J"]:
            return SimpleNamespace(returncode=0, stdout=json.dumps({"tracks": [
                {"id": 0, "type": "video"},
                {"id": 4, "type": "subtitles"},
                {"id": 9, "type": "subtitles"},
            ]}), aborted=False, timed_out=False)
        stage = Path(cmd[cmd.index("-o") + 1])
        stage.write_bytes(b"mks")
        return SimpleNamespace(returncode=0, stdout="", stderr="", aborted=False, timed_out=False)

    monkeypatch.setattr(extractor, "run_tool", fake_run_tool)
    monkeypatch.setattr(extractor, "verify_extraction", lambda *_a, **_k: True)

    assert extractor.extract_to_mks_with_mkvmerge(
        str(source), 7, str(output), mkvmerge="mkvmerge", ffprobe="ffprobe"
    )
    mux_cmd = calls[-1]
    assert mux_cmd[mux_cmd.index("--subtitle-tracks") + 1] == "9"
    assert "7" not in mux_cmd[mux_cmd.index("--subtitle-tracks") + 1:mux_cmd.index("--subtitle-tracks") + 2]
    assert output.read_bytes() == b"mks"

def test_extract_worker_uses_native_then_lossless_fallback(monkeypatch, tmp_path):
    pytest.importorskip("PyQt6")
    from dragontools.gui import subtitle_widget_workers as module

    source = tmp_path / "movie.mp4"
    source.write_bytes(b"video")
    tools = SimpleNamespace(ffprobe="ffprobe", ffmpeg="ffmpeg", mkvmerge="mkvmerge")
    streams = [
        {"index": 3, "codec_name": "webvtt", "codec_tag_string": "wvtt", "tags": {"language": "eng"}},
        {"index": 4, "codec_name": "hdmv_pgs_subtitle", "tags": {"language": "deu"}},
        {"index": 5, "codec_name": "future_codec", "tags": {"language": "jpn"}},
    ]

    def fake_run_tool(cmd, **_kwargs):
        assert cmd[0] == "ffprobe"
        return SimpleNamespace(
            ok=True,
            aborted=False,
            returncode=0,
            stdout=json.dumps({"streams": streams}),
            stderr="",
            tail=lambda _n: "",
        )

    attempts = []

    def fake_extract(_input, stream_index, output, _ffmpeg, **kwargs):
        attempts.append((stream_index, Path(output).suffix, tuple(kwargs["codec_args"])))
        # Native VTT and PGS work; unknown succeeds via generic .mks.
        return Path(output).suffix in {".vtt", ".sup", ".mks"}

    monkeypatch.setattr(module, "run_tool", fake_run_tool)
    monkeypatch.setattr(module, "extract_with_ffmpeg", fake_extract)
    monkeypatch.setattr(module, "extract_to_mks_with_mkvmerge", lambda *_a, **_k: False)

    worker = module._ExtractWorker([str(source)], str(tmp_path / "out"), tools)
    worker.run()

    assert (3, ".vtt", ("-c:s", "webvtt")) in attempts
    assert (4, ".sup", ("-c:s", "copy")) in attempts
    assert any(index == 5 and suffix == ".mks" and "copy" in args for index, suffix, args in attempts)


def test_mp4_bitmap_injection_automatically_outputs_mkv(monkeypatch, tmp_path):
    pytest.importorskip("PyQt6")
    from dragontools.gui import subtitle_widget_workers as module

    video = tmp_path / "movie.mp4"
    sub = tmp_path / "movie.de.sup"
    video.write_bytes(b"video")
    sub.write_bytes(b"pgs")
    tools = SimpleNamespace(ffprobe="ffprobe", ffmpeg="ffmpeg", mkvmerge="mkvmerge")

    monkeypatch.setattr(
        module,
        "probe_streams",
        lambda *_a, **_k: [{"index": 0, "codec_type": "subtitle", "codec_name": "hdmv_pgs_subtitle"}],
    )
    calls = []

    def fake_mkv(video_path, sub_path, output_path, *args, **kwargs):
        calls.append((video_path, sub_path, output_path, args, kwargs))
        return True

    monkeypatch.setattr(module, "inject_with_mkvmerge", fake_mkv)
    monkeypatch.setattr(module, "inject_with_ffmpeg", lambda *_a, **_k: pytest.fail("bitmap subtitle must not be forced into MP4"))

    worker = module._InjectWorker([str(video)], str(sub), "deu", False, tools, title="Deutsch")
    worker.run()

    assert len(calls) == 1
    assert Path(calls[0][2]).suffix == ".mkv"


def test_mp4_webvtt_injection_targets_new_subtitle_as_mov_text(monkeypatch, tmp_path):
    pytest.importorskip("PyQt6")
    from dragontools.gui import subtitle_widget_workers as module

    video = tmp_path / "movie.mp4"
    sub = tmp_path / "movie.de.vtt"
    video.write_bytes(b"video")
    sub.write_text("WEBVTT\n", encoding="utf-8")
    tools = SimpleNamespace(ffprobe="ffprobe", ffmpeg="ffmpeg", mkvmerge="mkvmerge")

    monkeypatch.setattr(
        module,
        "probe_streams",
        lambda *_a, **_k: [{"index": 0, "codec_type": "subtitle", "codec_name": "webvtt", "codec_tag_string": "wvtt"}],
    )
    calls = []

    def fake_ffmpeg(*args, **kwargs):
        calls.append((args, kwargs))
        return True

    monkeypatch.setattr(module, "inject_with_ffmpeg", fake_ffmpeg)
    monkeypatch.setattr(module, "inject_with_mkvmerge", lambda *_a, **_k: pytest.fail("text subtitle should stay MP4 when FFmpeg succeeds"))

    worker = module._InjectWorker([str(video)], str(sub), "deu", True, tools, title="Deutsch")
    worker.run()

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert Path(args[2]).suffix == ".mp4"
    assert kwargs["subtitle_codec"] == "mov_text"
    assert kwargs["forced"] is True


@pytest.mark.skipif(importlib.util.find_spec("PyQt6") is None, reason="PyQt6 unavailable")
def test_middle_click_closes_exactly_one_tab(qtbot):
    from PyQt6.QtCore import Qt
    from dragontools.gui.main_window_tabs import _TabBar

    bar = _TabBar()
    qtbot.addWidget(bar)
    for label in ("A", "B", "C", "D"):
        bar.addTab(label)
    bar.resize(600, 40)
    bar.show()

    closed = []

    def close_one(index):
        closed.append(index)
        bar.removeTab(index)

    bar.tabCloseRequested.connect(close_one)
    position = bar.tabRect(1).center()
    qtbot.mouseClick(bar, Qt.MouseButton.MiddleButton, pos=position)

    assert closed == [1]
    assert bar.count() == 3
    assert [bar.tabText(i) for i in range(bar.count())] == ["A", "C", "D"]
