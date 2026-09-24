from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from dragontools.worker.duration_repair_stream_guard import RepairStreamGuard


class Analyzer:
    def __init__(self, ffprobe_by_path, mediainfo_by_path):
        self.ffprobe_by_path = ffprobe_by_path
        self.mediainfo_by_path = mediainfo_by_path

    def run_ffprobe_json(self, path, count_frames=False):
        return self.ffprobe_by_path[path]

    def run_mediainfo_json(self, path):
        return self.mediainfo_by_path[path]


def _ff(v=1, a=1, s=1):
    streams = (
        [{"codec_type": "video"}] * v
        + [{"codec_type": "audio"}] * a
        + [{"codec_type": "subtitle"}] * s
    )
    return {"streams": streams}


def _mi(v=1, a=1, s=1):
    tracks = (
        [{"@type": "Video"}] * v
        + [{"@type": "Audio"}] * a
        + [{"@type": "Text"}] * s
    )
    return {"media": {"track": tracks}}


def _mkv(v=1, a=1, s=1):
    tracks = (
        [{"id": i, "type": "video"} for i in range(v)]
        + [{"id": 10 + i, "type": "audio"} for i in range(a)]
        + [{"id": 20 + i, "type": "subtitles"} for i in range(s)]
    )
    return {"tracks": tracks}


@pytest.fixture(autouse=True)
def _tools_available(monkeypatch):
    monkeypatch.setattr(
        "dragontools.worker.duration_repair_stream_guard.tool_available",
        lambda _path: True,
    )


def test_disagreeing_stream_tools_accept_when_one_tool_confirms_presence():
    analyzer = Analyzer(
        {"before": _ff(1, 2, 1), "after": _ff(1, 1, 1)},
        {"before": _mi(1, 2, 1), "after": _mi(1, 2, 1)},
    )
    guard = RepairStreamGuard(
        timing_analyzer=analyzer,
        ffprobe_path="ffprobe",
        mediainfo_path="mediainfo",
        log=lambda *_: None,
    )
    before_ff, before_mi = guard.inspect_pair("before")
    result = guard.validate(
        before_ffprobe=before_ff,
        before_mediainfo=before_mi,
        candidate_path="after",
    )

    assert result.ok is True
    assert result.retry_recommended is False
    assert "audio" in result.confirmed_kinds
    assert any("Parser-Widerspruch" in msg for msg in result.messages)


def test_missing_stream_is_not_declared_lost_until_all_three_tools_agree():
    analyzer = Analyzer(
        {"before": _ff(1, 2, 1), "after": _ff(1, 1, 0)},
        {"before": _mi(1, 2, 1), "after": _mi(1, 1, 0)},
    )
    guard = RepairStreamGuard(
        timing_analyzer=analyzer,
        ffprobe_path="ffprobe",
        mediainfo_path="mediainfo",
        log=lambda *_: None,
    )
    before_ff, before_mi = guard.inspect_pair("before")
    result = guard.validate(
        before_ffprobe=before_ff,
        before_mediainfo=before_mi,
        candidate_path="after",
    )

    assert result.ok is True
    assert any("Kein 3-von-3-Verlustnachweis" in msg for msg in result.messages)


def test_all_three_tools_must_agree_before_stream_is_rejected():
    analyzer = Analyzer(
        {"before": _ff(1, 2, 1), "after": _ff(1, 1, 0)},
        {"before": _mi(1, 2, 1), "after": _mi(1, 1, 0)},
    )

    def run_tool(cmd, *, label):
        path = str(cmd[-1])
        payload = _mkv(1, 2, 1) if path == "before" else _mkv(1, 1, 0)
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    guard = RepairStreamGuard(
        timing_analyzer=analyzer,
        ffprobe_path="ffprobe",
        mediainfo_path="mediainfo",
        mkvmerge_path="mkvmerge",
        run_tool_fn=run_tool,
        log=lambda *_: None,
    )
    before_ff, before_mi, before_mkv = guard.inspect_all("before")
    result = guard.validate(
        before_ffprobe=before_ff,
        before_mediainfo=before_mi,
        before_mkvmerge=before_mkv,
        candidate_path="after",
    )

    assert result.ok is False
    assert result.retry_recommended is True
    assert any("Alle drei Prüfwerkzeuge" in msg and "Audiospuren" in msg for msg in result.messages)
    assert any("Alle drei Prüfwerkzeuge" in msg and "Untertitelspuren" in msg for msg in result.messages)
