from __future__ import annotations

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


@pytest.fixture(autouse=True)
def _tools_available(monkeypatch):
    monkeypatch.setattr(
        "dragontools.worker.duration_repair_stream_guard.tool_available",
        lambda _path: True,
    )


def test_disagreeing_stream_tools_reject_candidate_fail_closed():
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

    assert result.ok is False
    assert result.retry_recommended is True
    assert any("widersprechen" in msg for msg in result.messages)


def test_mediainfo_confirmed_stream_loss_forces_retry_and_reject():
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

    assert result.ok is False
    assert result.retry_recommended is True
    assert any("MediaInfo bestätigt fehlende Audiospuren" in msg for msg in result.messages)
    assert any("MediaInfo bestätigt fehlende Untertitelspuren" in msg for msg in result.messages)
