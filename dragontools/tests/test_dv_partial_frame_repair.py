from __future__ import annotations

import random
from pathlib import Path
from types import SimpleNamespace

from dragontools.worker.dv_partial_frame_repair import (
    DVPartialFrameRepair,
    GapRegion,
    IrapPoint,
    choose_repair_window,
    locate_deleted_region,
)
from dragontools.worker.dv_pipeline_context import DVWorkFiles
from dragontools.worker.dv_runtime_models import DVEncoderConfig


def _cfg() -> DVEncoderConfig:
    return DVEncoderConfig(
        codec="h265",
        crf=22,
        preset="medium",
        options={"encoder": "cpu", "bf": 8},
    )


def test_locate_deleted_region_handles_many_distributed_missing_frames():
    rng = random.Random(12345)
    source = [rng.getrandbits(64) for _ in range(12_000)]
    # Model the Mononoke-style failure: many individual dropped pictures spread
    # over one bounded interval, not one contiguous missing chunk.
    missing = {
        round(3_000 + i * (2_400 / 207))
        for i in range(208)
    }
    encoded = [value for index, value in enumerate(source) if index not in missing]
    delta = len(source) - len(encoded)

    region = locate_deleted_region(source, encoded, expected_delta=delta, stride=24)

    assert region is not None
    assert region.delta == delta
    assert region.encoded_start < 3_000
    assert region.encoded_end > 5_000 - delta
    assert region.observations > 50


def test_choose_repair_window_expands_to_irap_and_maps_source_delta():
    region = GapRegion(encoded_start=2_900, encoded_end=4_900, delta=362, observations=100)
    iraps = [
        IrapPoint(frame_index=2_640, byte_offset=100, nal_type=19),
        IrapPoint(frame_index=2_880, byte_offset=200, nal_type=21),
        IrapPoint(frame_index=5_040, byte_offset=300, nal_type=19),
    ]

    window = choose_repair_window(
        region=region,
        irap_points=iraps,
        encoded_frames=10_000,
        encoded_size=1_000,
        bframe_margin=16,
    )

    assert window is not None
    assert window.encoded_start == 2_880
    assert window.source_start == 2_880
    assert window.encoded_end == 5_040
    assert window.source_end == 5_040 + 362
    assert window.prefix_byte_end == 200
    assert window.suffix_byte_start == 300
    assert window.suffix_is_strong_boundary is True


def test_p5_partial_repair_uses_same_libplacebo_filter_for_source_fingerprint(tmp_path, monkeypatch):
    files = DVWorkFiles.create(tmp_path)
    files.enc_hevc.write_bytes(b"encoded")
    request = SimpleNamespace(
        input_path=str(tmp_path / "movie.mkv"),
        profile_major=5,
        vf_args=["-vf", "crop=3840:2076:0:42"],
    )
    Path(request.input_path).write_bytes(b"source")
    state = SimpleNamespace(
        request=request,
        files=files,
        effective_vf_args=list(request.vf_args),
    )
    seen: list[tuple[str, str]] = []
    repair = DVPartialFrameRepair(
        tools=SimpleNamespace(ffmpeg="ffmpeg"),
        encoder_config=_cfg(),
        progress_runner=SimpleNamespace(),
        log=lambda *_args, **_kwargs: None,
        verbose_log=lambda *_args, **_kwargs: None,
    )

    def stop_after_source_fingerprint(_runner, *, input_path, output_path, source_vf=""):
        seen.append((input_path, source_vf))
        return False

    monkeypatch.setattr(repair, "_write_fingerprint", stop_after_source_fingerprint)

    assert repair.attempt(
        state=state,
        runner=SimpleNamespace(),
        expected_rpu_frames=1_000,
        actual_encode_frames=990,
    ) is False
    assert seen
    assert seen[0][0] == request.input_path
    assert "libplacebo=" in seen[0][1]
    assert "crop=3840:2076:0:42" in seen[0][1]


def test_partial_repair_skips_filter_complex_instead_of_raw_splicing_unsafely(tmp_path):
    files = DVWorkFiles.create(tmp_path)
    files.enc_hevc.write_bytes(b"encoded")
    request = SimpleNamespace(
        input_path=str(tmp_path / "movie.mkv"),
        profile_major=8,
        vf_args=[
            "-filter_complex",
            "[0:v:0]crop=3840:2076:0:42[v];[v][0:s:0]overlay[vout]",
            "-map", "[vout]",
        ],
    )
    Path(request.input_path).write_bytes(b"source")
    logs: list[str] = []
    repair = DVPartialFrameRepair(
        tools=SimpleNamespace(ffmpeg="ffmpeg"),
        encoder_config=_cfg(),
        progress_runner=SimpleNamespace(),
        log=lambda *_args, **_kwargs: None,
        verbose_log=lambda message: logs.append(message),
    )
    state = SimpleNamespace(request=request, files=files, effective_vf_args=list(request.vf_args))

    assert repair.attempt(
        state=state,
        runner=SimpleNamespace(),
        expected_rpu_frames=1_000,
        actual_encode_frames=990,
    ) is False
    assert any("filter_complex" in line for line in logs)
