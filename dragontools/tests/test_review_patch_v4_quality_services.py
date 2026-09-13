from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace


def _media(path: str, *, duration: float = 60.0):
    return SimpleNamespace(
        size_bytes=Path(path).stat().st_size,
        duration_s=duration,
        primary_video=SimpleNamespace(width=1920, height=1080, codec="h265", pix_fmt="yuv420p10le", frame_rate="24"),
        video_streams=[],
        has_dv=False,
        has_hdrplus=False,
        is_hdr=False,
    )


def test_quality_compare_service_emits_result_and_summary(monkeypatch, tmp_path):
    import dragontools.worker.quality_compare_service as module

    a = tmp_path / "a.mkv"; b = tmp_path / "b.mkv"
    a.write_bytes(b"a" * 100); b.write_bytes(b"b" * 80)
    monkeypatch.setattr(module, "analyze_media", lambda path, _tools: _media(path))

    class Metrics:
        def measure_comparison(self, *, metric, **_kwargs):
            return 0.99 if metric == "ssim" else 95.0

    results, summaries, progress, logs = [], [], [], []
    service = module.QualityCompareService(
        tools=SimpleNamespace(), metrics=Metrics(), log=logs.append, progress=progress.append,
        result_ready=results.append, summary_ready=summaries.append, is_aborted=lambda: False,
    )
    service.run(file_a=str(a), file_b=str(b), sample_count=1, sample_duration_s=10, manual_ranges="", offset_b_s=0.0)

    assert len(results) == 1
    assert results[0].ssim == 0.99 and results[0].vmaf == 95.0
    assert len(summaries) == 1 and summaries[0].compared_segments == 1
    assert summaries[0].average_ssim == 0.99 and summaries[0].average_vmaf == 95.0
    assert progress[-1] == 100


def test_quality_test_service_runs_encode_probe_and_metrics(monkeypatch, tmp_path):
    import dragontools.worker.quality_test_service as module
    from dragontools.core.quality_tester import quality_run_from_dict

    source = tmp_path / "source.mkv"; source.write_bytes(b"src")
    monkeypatch.setattr(module, "analyze_media", lambda path, _tools: _media(path, duration=30.0))

    class Runner:
        def run(self, cmd, *, label):
            if label == "Encode":
                Path(cmd[-1]).write_bytes(b"encoded" * 100)
                return 0, "", ""
            if label == "ffprobe":
                payload = {"streams": [{"codec_type": "video", "codec_name": "hevc", "pix_fmt": "yuv420p10le", "profile": "Main 10", "width": 1920, "height": 1080}], "format": {"duration": "10.0", "bit_rate": "800000"}}
                return 0, json.dumps(payload), ""
            raise AssertionError(label)

    class Metrics:
        def measure_encoded(self, *, metric, **_kwargs):
            return 0.98 if metric == "ssim" else 93.5

    run = quality_run_from_dict({"name": "Test", "codec": "h265", "encoder": "cpu", "quality": 23, "preset": "medium"})
    emitted, progress, logs = [], [], []
    service = module.QualityTestService(
        tools=SimpleNamespace(ffmpeg="ffmpeg", ffprobe="ffprobe"), process_runner=Runner(), metrics=Metrics(),
        log=logs.append, progress=progress.append, result_ready=emitted.append, is_aborted=lambda: False,
    )
    service.run(files=[str(source)], output_dir=str(tmp_path / "out"), runs=[run], sample_count=1, sample_duration_s=10, manual_ranges="")

    assert len(emitted) == 1
    result = emitted[0]
    assert result.codec == "hevc" and result.ssim == 0.98 and result.vmaf == 93.5
    assert result.video_bitrate_kbps == 800.0
    assert progress[-1] == 100


def test_quality_metrics_service_parses_ffmpeg_metric_output():
    from dragontools.worker.quality_metrics_service import QualityMetricsService

    class Runner:
        def run(self, _cmd, *, label):
            if "SSIM" in label:
                return 0, "", "SSIM Y:0.99 All:0.98765 (19.2)"
            return 0, "", "VMAF score: 96.42"

    service = QualityMetricsService(ffmpeg="ffmpeg", process_runner=Runner())
    notes = []
    ssim = service.measure_comparison(metric="ssim", file_a="a", file_b="b", start_a=0, start_b=0,
        duration=1, width=1920, height=1080, label="SSIM", notes=notes)
    vmaf = service.measure_comparison(metric="libvmaf", file_a="a", file_b="b", start_a=0, start_b=0,
        duration=1, width=1920, height=1080, label="VMAF", notes=notes)
    assert ssim == 0.98765
    assert vmaf == 96.42
    assert notes == []
