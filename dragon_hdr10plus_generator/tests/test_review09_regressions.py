from __future__ import annotations

import json

from dragon_hdr10plus_generator.analyzer.decoder import VideoProbe
from dragon_hdr10plus_generator.analyzer.scanner import FrameStatistics, ScanResult
from dragon_hdr10plus_generator.cli import main
from dragon_hdr10plus_generator.metadata.st2094_40 import build_st2094_40_metadata


def _frame(index: int, value: float = 100.0) -> FrameStatistics:
    return FrameStatistics(
        index=index,
        max_scl_nits=(value, value, value),
        average_maxrgb_nits=value,
        p01_nits=value,
        p25_nits=value,
        p50_nits=value,
        p75_nits=value,
        p90_nits=value,
        p95_nits=value,
        p9998_nits=value,
        p9999_nits=value,
        below_100_nits_percent=50.0,
        histogram=(1.0, 0.0),
    )


def test_cli_rejects_reliable_probe_vs_decoded_frame_mismatch(tmp_path, capsys, monkeypatch):
    import dragon_hdr10plus_generator.cli as cli_module

    source = tmp_path / "source.mkv"
    output = tmp_path / "hdr10plus.json"
    source.write_bytes(b"video")
    monkeypatch.setattr(
        cli_module,
        "probe_video",
        lambda *_a, **_k: VideoProbe(
            transfer="smpte2084", primaries="bt2020", pixel_format="yuv420p10le",
            bit_depth=10, frames=3, width=1920, height=1080, fps=24.0, codec="hevc",
            profile="Main 10", color_space="bt2020nc",
            frame_count_source="stream_nb_frames", frame_count_reliability="reported",
        ),
    )
    monkeypatch.setattr(
        cli_module,
        "scan_pq_video",
        lambda *_a, **_k: ScanResult(tuple(_frame(i) for i in range(2)), 256, 144),
    )

    assert main(["analyze", "--input", str(source), "--output", str(output)]) == 2
    response = json.loads(capsys.readouterr().out)
    assert response["error"] == "FRAME_COUNT_MISMATCH"
    assert response["reported_frames"] == 3 and response["decoded_frames"] == 2
    assert not output.exists()


def test_generated_st2094_ranges_are_clamped_for_extreme_measurements():
    frame = FrameStatistics(
        index=0,
        max_scl_nits=(-1.0, 50_000.0, 100.0),
        average_maxrgb_nits=50_000.0,
        p01_nits=-100.0,
        p25_nits=20_000.0,
        p50_nits=20_000.0,
        p75_nits=20_000.0,
        p90_nits=20_000.0,
        p95_nits=20_000.0,
        p9998_nits=20_000.0,
        p9999_nits=20_000.0,
        below_100_nits_percent=500.0,
        histogram=(1.0, 0.0),
    )
    payload = build_st2094_40_metadata((frame,))
    scene = payload["SceneInfo"][0]
    lum = scene["LuminanceParameters"]
    assert all(0 <= value <= 100_000 for value in lum["MaxScl"])
    assert 0 <= lum["AverageRGB"] <= 100_000
    dist = lum["LuminanceDistributions"]["DistributionValues"]
    assert all(0 <= value <= 100_000 for value in dist)
    assert dist[2] == 100
