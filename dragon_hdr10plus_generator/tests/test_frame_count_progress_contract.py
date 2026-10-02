from __future__ import annotations

from dragon_hdr10plus_generator.analyzer.decoder import VideoProbe
from dragon_hdr10plus_generator.analyzer.scanner import _progress_message


def test_unknown_total_has_activity_without_fake_percent_or_eta():
    text = _progress_message(current=12345, expected=0, reliability="unknown", fps=8.5, elapsed=1200)
    assert "12345 frames" in text
    assert "8.5 fps" in text
    assert "%" not in text
    assert "ETA" not in text


def test_estimated_total_is_explicitly_labeled_estimate():
    text = _progress_message(current=500, expected=1000, reliability="estimated", fps=10.0, elapsed=50)
    assert "50.0% (geschätzt)" in text
    assert "ETA" in text
    assert text.endswith("(geschätzt)")


def test_exceeded_estimate_stops_showing_fake_percent_and_eta():
    text = _progress_message(current=1100, expected=1000, reliability="estimated", fps=10.0, elapsed=110)
    assert "Gesamtschätzung überschritten" in text
    assert "%" not in text
    assert "ETA" not in text


def test_probe_contract_distinguishes_unknown_estimated_and_reported():
    unknown = VideoProbe("smpte2084", "bt2020", "yuv420p10le", 10, None, frame_count_source="unknown", frame_count_reliability="unknown")
    estimated = VideoProbe("smpte2084", "bt2020", "yuv420p10le", 10, 1000, frame_count_source="duration_x_fps", frame_count_reliability="estimated")
    reported = VideoProbe("smpte2084", "bt2020", "yuv420p10le", 10, 1000, frame_count_source="stream_nb_frames", frame_count_reliability="reported")
    assert unknown.frame_count_reliability == "unknown"
    assert estimated.frame_count_reliability == "estimated"
    assert reported.frame_count_reliability == "reported"


def test_raw_hevc_without_duration_keeps_total_unknown(tmp_path, monkeypatch):
    import json
    from dragon_hdr10plus_generator.analyzer import decoder

    source = tmp_path / "encoded.hevc"
    source.write_bytes(b"hevc")

    class Result:
        returncode = 0
        stderr = ""
        stdout = json.dumps({
            "streams": [{
                "codec_name": "hevc",
                "profile": "Main 10",
                "width": 3840,
                "height": 2160,
                "color_transfer": "smpte2084",
                "color_primaries": "bt2020",
                "pix_fmt": "yuv420p10le",
                "avg_frame_rate": "24000/1001",
            }],
            "format": {},
        })

    monkeypatch.setattr(decoder.subprocess, "run", lambda *_a, **_k: Result())
    probe = decoder.probe_video(source)
    assert probe.frames is None
    assert probe.frame_count_source == "unknown"
    assert probe.frame_count_reliability == "unknown"


def test_duration_times_fps_is_only_estimated_even_when_rounded(tmp_path, monkeypatch):
    import json
    from dragon_hdr10plus_generator.analyzer import decoder

    source = tmp_path / "container.mkv"
    source.write_bytes(b"container")

    class Result:
        returncode = 0
        stderr = ""
        stdout = json.dumps({
            "streams": [{
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "24000/1001",
                "r_frame_rate": "24/1",
            }],
            "format": {"duration": "100.04"},
        })

    monkeypatch.setattr(decoder.subprocess, "run", lambda *_a, **_k: Result())
    probe = decoder.probe_video(source)
    assert probe.frames == round(100.04 * (24000 / 1001))
    assert probe.frame_count_reliability == "estimated"
    assert probe.frame_count_source == "duration_x_fps"


def test_reported_metadata_total_is_labeled_as_metadata():
    text = _progress_message(current=500, expected=1000, reliability="reported", fps=10.0, elapsed=50)
    assert "50.0% (Metadaten)" in text
    assert text.endswith("(Metadaten)")
