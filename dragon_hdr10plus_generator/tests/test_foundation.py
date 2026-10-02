from __future__ import annotations

import json

import pytest

from dragon_hdr10plus_generator.analyzer.luminance import pq_eotf, pq_oetf
from dragon_hdr10plus_generator.analyzer.scanner import FrameStatistics
from dragon_hdr10plus_generator.analyzer.statistics import percentile, summarize_distribution
from dragon_hdr10plus_generator.cli import main
from dragon_hdr10plus_generator.metadata.st2094_40 import (
    DISTRIBUTION_INDEX,
    build_st2094_40_metadata,
    detect_scenes,
)


def _frame(index: int, value: float, hist: tuple[float, ...] = (1.0, 0.0)) -> FrameStatistics:
    return FrameStatistics(
        index=index,
        max_scl_nits=(value + 10, value + 20, value + 30),
        average_maxrgb_nits=value,
        p01_nits=value * 0.01,
        p25_nits=value * 0.25,
        p50_nits=value * 0.5,
        p75_nits=value * 0.75,
        p90_nits=value * 0.9,
        p95_nits=value * 0.95,
        p9998_nits=value * 0.9998,
        p9999_nits=value * 0.9999,
        below_100_nits_percent=80.0,
        histogram=hist,
    )


def test_pq_endpoints_and_roundtrip():
    assert pq_eotf(0.0) == pytest.approx(0.0, abs=1e-9)
    assert pq_eotf(1.0) == pytest.approx(10000.0, rel=1e-6)
    for nits in (0.1, 100.0, 1000.0, 4000.0):
        assert pq_eotf(pq_oetf(nits)) == pytest.approx(nits, rel=1e-6, abs=1e-6)


def test_distribution_keeps_peak_separate_from_robust_percentiles():
    samples = [100.0] * 999 + [10000.0]
    summary = summarize_distribution(samples, percentile_points=(99.0, 99.9))
    assert summary.maximum == 10000.0
    assert summary.percentiles[99.0] == pytest.approx(100.0)
    assert 100.0 < summary.percentiles[99.9] < 10000.0
    assert percentile(samples, 50.0) == 100.0


def test_version_is_structured_json(capsys):
    assert main(["--version"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"success": True, "version": "0.2.0"}


def test_analyze_missing_input_is_structured_and_writes_nothing(tmp_path, capsys):
    output = tmp_path / "hdr10plus.json"
    assert main(["analyze", "--input", str(tmp_path / "missing.mkv"), "--output", str(output)]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is False
    assert payload["error"] == "INPUT_NOT_FOUND"
    assert not output.exists()


def test_scene_detection_respects_histogram_cut():
    frames = tuple(
        [_frame(i, 100.0, (1.0, 0.0)) for i in range(6)]
        + [_frame(i, 500.0, (0.0, 1.0)) for i in range(6, 12)]
    )
    scenes = detect_scenes(frames, threshold=0.5, min_scene_frames=3)
    assert [(s.start, s.end) for s in scenes] == [(0, 6), (6, 12)]


def test_profile_a_json_has_one_entry_per_frame_and_canonical_distributions():
    frames = tuple(_frame(i, 100.0 + i) for i in range(8))
    payload = build_st2094_40_metadata(frames, min_scene_frames=2)
    assert payload["JSONInfo"] == {"HDR10plusProfile": "A", "Version": "1.0"}
    assert len(payload["SceneInfo"]) == len(frames)
    first = payload["SceneInfo"][0]
    assert first["SequenceFrameIndex"] == 0
    assert first["LuminanceParameters"]["LuminanceDistributions"]["DistributionIndex"] == DISTRIBUTION_INDEX
    assert 0 <= first["LuminanceParameters"]["LuminanceDistributions"]["DistributionValues"][2] <= 100
    assert "BezierCurveData" not in first


def test_analyze_pq_source_writes_generated_json(tmp_path, capsys, monkeypatch):
    from dragon_hdr10plus_generator.analyzer.decoder import VideoProbe
    from dragon_hdr10plus_generator.analyzer.scanner import ScanResult
    import dragon_hdr10plus_generator.cli as cli_module

    source = tmp_path / "PQ Quelle ä.mp4"
    source.write_bytes(b"video-marker")
    output = tmp_path / "hdr10plus.json"
    monkeypatch.setattr(
        cli_module,
        "probe_video",
        lambda *_args, **_kwargs: VideoProbe(
            transfer="smpte2084",
            primaries="bt2020",
            pixel_format="yuv420p10le",
            bit_depth=10,
            frames=3,
            width=1920,
            height=1080,
            fps=24.0,
            codec="hevc",
        ),
    )
    monkeypatch.setattr(
        cli_module,
        "scan_pq_video",
        lambda *_args, **_kwargs: ScanResult(tuple(_frame(i, 200.0) for i in range(3)), 256, 144),
    )

    assert main(["analyze", "--input", str(source), "--output", str(output)]) == 0
    response = json.loads(capsys.readouterr().out)
    assert response["success"] is True
    assert response["frames"] == 3
    assert response["scenes"] == 1
    assert response["profile"] == "A"
    metadata = json.loads(output.read_text(encoding="utf-8"))
    assert len(metadata["SceneInfo"]) == 3



def _probe(*, primaries: str = "bt2020", width: int | None = 1920, height: int | None = 1080):
    from dragon_hdr10plus_generator.analyzer.decoder import VideoProbe

    return VideoProbe(
        transfer="smpte2084",
        primaries=primaries,
        pixel_format="yuv420p10le",
        bit_depth=10,
        frames=3,
        width=width,
        height=height,
        fps=24.0,
        codec="hevc",
    )


def test_analyze_rejects_missing_bt2020_primaries_fail_closed(tmp_path, capsys, monkeypatch):
    import dragon_hdr10plus_generator.cli as cli_module

    source = tmp_path / "pq-without-primaries.mkv"
    source.write_bytes(b"video")
    output = tmp_path / "hdr10plus.json"
    monkeypatch.setattr(cli_module, "probe_video", lambda *_args, **_kwargs: _probe(primaries=""))
    monkeypatch.setattr(
        cli_module,
        "scan_pq_video",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("scan must not start")),
    )

    assert main(["analyze", "--input", str(source), "--output", str(output)]) == 2
    response = json.loads(capsys.readouterr().out)
    assert response["error"] == "SOURCE_NOT_BT2020"
    assert response["primaries"] == ""
    assert not output.exists()


def test_analyze_rejects_missing_probe_dimensions_instead_of_inventing_1080p(tmp_path, capsys, monkeypatch):
    import dragon_hdr10plus_generator.cli as cli_module

    source = tmp_path / "pq-without-dimensions.mkv"
    source.write_bytes(b"video")
    output = tmp_path / "hdr10plus.json"
    monkeypatch.setattr(cli_module, "probe_video", lambda *_args, **_kwargs: _probe(width=None, height=None))
    monkeypatch.setattr(
        cli_module,
        "scan_pq_video",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("scan must not start")),
    )

    assert main(["analyze", "--input", str(source), "--output", str(output)]) == 2
    response = json.loads(capsys.readouterr().out)
    assert response["error"] == "PROBE_INCOMPLETE"
    assert response["width"] is None and response["height"] is None
    assert not output.exists()


def test_analyze_distinguishes_missing_ffprobe_from_missing_input(tmp_path, capsys, monkeypatch):
    import dragon_hdr10plus_generator.cli as cli_module
    from dragon_hdr10plus_generator.analyzer.decoder import ProbeToolNotFoundError

    source = tmp_path / "source.mkv"
    source.write_bytes(b"video")
    output = tmp_path / "hdr10plus.json"
    monkeypatch.setattr(
        cli_module,
        "probe_video",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ProbeToolNotFoundError("ffprobe")),
    )

    assert main(["analyze", "--input", str(source), "--output", str(output)]) == 2
    response = json.loads(capsys.readouterr().out)
    assert response["error"] == "TOOL_NOT_FOUND"
    assert not output.exists()


def test_analyze_reports_probe_timeout_explicitly(tmp_path, capsys, monkeypatch):
    import dragon_hdr10plus_generator.cli as cli_module
    from dragon_hdr10plus_generator.analyzer.decoder import ProbeTimeoutError

    source = tmp_path / "source.mkv"
    source.write_bytes(b"video")
    output = tmp_path / "hdr10plus.json"
    monkeypatch.setattr(
        cli_module,
        "probe_video",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ProbeTimeoutError("ffprobe timeout")),
    )

    assert main(["analyze", "--input", str(source), "--output", str(output)]) == 2
    response = json.loads(capsys.readouterr().out)
    assert response["error"] == "PROBE_TIMEOUT"


def test_probe_video_passes_bounded_timeout_and_classifies_missing_tool(tmp_path, monkeypatch):
    import subprocess
    import dragon_hdr10plus_generator.analyzer.decoder as decoder

    source = tmp_path / "source.mkv"
    source.write_bytes(b"video")
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = list(command)
        seen.update(kwargs)
        raise FileNotFoundError("ffprobe")

    monkeypatch.setattr(decoder.subprocess, "run", fake_run)
    with pytest.raises(decoder.ProbeToolNotFoundError):
        decoder.probe_video(source, ffprobe="missing-ffprobe", timeout_s=12.5)
    assert seen["command"][0] == "missing-ffprobe"
    assert seen["timeout"] == pytest.approx(12.5)


def test_probe_video_classifies_subprocess_timeout(tmp_path, monkeypatch):
    import subprocess
    import dragon_hdr10plus_generator.analyzer.decoder as decoder

    source = tmp_path / "source.mkv"
    source.write_bytes(b"video")

    def fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs.get("timeout", 0))

    monkeypatch.setattr(decoder.subprocess, "run", fake_run)
    with pytest.raises(decoder.ProbeTimeoutError, match="ffprobe timeout"):
        decoder.probe_video(source, timeout_s=0.5)


def test_scanner_rejects_missing_dimensions_defensively(tmp_path):
    import dragon_hdr10plus_generator.analyzer.scanner as scanner

    source = tmp_path / "source.mkv"
    source.write_bytes(b"video")
    with pytest.raises(ValueError, match="PROBE_DIMENSIONS_MISSING"):
        scanner.scan_pq_video(source, _probe(width=None, height=1080))


def test_scanner_inactivity_watchdog_terminates_stalled_ffmpeg(tmp_path, monkeypatch):
    import io
    import threading
    import dragon_hdr10plus_generator.analyzer.scanner as scanner

    source = tmp_path / "source.mkv"
    source.write_bytes(b"video")

    class BlockingStdout:
        def __init__(self):
            self.released = threading.Event()

        def read(self, _size=-1):
            self.released.wait(5.0)
            return b""

        def close(self):
            self.released.set()

    class FakeProcess:
        def __init__(self):
            self.stdout = BlockingStdout()
            self.stderr = io.BytesIO(b"decoder stalled\n" * 10000)
            self.returncode = None
            self.killed = False

        def poll(self):
            return self.returncode

        def kill(self):
            self.killed = True
            self.returncode = -9
            self.stdout.close()

        def wait(self, timeout=None):
            if self.returncode is None:
                if timeout is not None:
                    raise scanner.subprocess.TimeoutExpired(["ffmpeg"], timeout)
                self.returncode = 0
            return self.returncode

    process = FakeProcess()
    monkeypatch.setattr(scanner.subprocess, "Popen", lambda *_args, **_kwargs: process)

    with pytest.raises(scanner.FFmpegInactivityTimeoutError):
        scanner.scan_pq_video(
            source,
            _probe(width=64, height=64),
            analysis_width=64,
            inactivity_timeout_s=0.2,
        )
    assert process.killed is True


def test_analyze_rejects_explicit_8bit_pq_when_bits_per_raw_sample_is_missing(tmp_path, capsys, monkeypatch):
    from dragon_hdr10plus_generator.analyzer.decoder import VideoProbe
    import dragon_hdr10plus_generator.cli as cli_module

    source = tmp_path / "fake-8bit-pq.mkv"
    source.write_bytes(b"video")
    output = tmp_path / "hdr10plus.json"
    monkeypatch.setattr(
        cli_module,
        "probe_video",
        lambda *_args, **_kwargs: VideoProbe(
            transfer="smpte2084",
            primaries="bt2020",
            pixel_format="yuv420p",
            bit_depth=None,
            frames=24,
            width=1920,
            height=1080,
            fps=24.0,
            codec="hevc",
            profile="Main",
            color_space="bt2020nc",
        ),
    )
    monkeypatch.setattr(
        cli_module,
        "scan_pq_video",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("8-bit source must be rejected before scan")),
    )

    assert main(["analyze", "--input", str(source), "--output", str(output)]) == 2
    response = json.loads(capsys.readouterr().out)
    assert response["error"] == "SOURCE_BIT_DEPTH_UNEXPECTED"
    assert response["bit_depth"] == 8
    assert response["pixel_format"] == "yuv420p"
    assert not output.exists()


def test_bit_depth_inference_accepts_main10_pixel_formats():
    from dragon_hdr10plus_generator.cli import _infer_bit_depth

    assert _infer_bit_depth("yuv420p10le", "Main 10") == 10
    assert _infer_bit_depth("p010le", "Main 10") == 10
    assert _infer_bit_depth("yuv420p", "Main") == 8
