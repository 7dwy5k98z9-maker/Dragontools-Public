

def test_probe_command_does_not_force_full_frame_count_scan(tmp_path, monkeypatch):
    from dragon_hdr10plus_generator.analyzer import decoder

    source = tmp_path / "long_uhd.mkv"
    source.write_bytes(b"x")
    seen = {}

    class Result:
        returncode = 0
        stderr = ""
        stdout = '{"streams":[{"width":3840,"height":2160,"color_transfer":"smpte2084","color_primaries":"bt2020","avg_frame_rate":"24000/1001"}],"format":{"duration":"7200.0"}}'

    def fake_run(command, **kwargs):
        seen["command"] = command
        return Result()

    monkeypatch.setattr(decoder.subprocess, "run", fake_run)
    probe = decoder.probe_video(source, ffprobe="custom-ffprobe", timeout_s=30)
    assert "-count_frames" not in seen["command"]
    assert probe.frames is not None and probe.frames > 100000
    assert probe.duration_s == 7200.0


def test_histogram_storage_is_compact_uint32_without_changing_distance_semantics():
    import sys
    from array import array

    import numpy as np

    from dragon_hdr10plus_generator.analyzer.scanner import _histogram
    from dragon_hdr10plus_generator.analyzer.scene_detection import histogram_distance

    values = np.concatenate((np.full(75, 0.25, dtype=np.float32), np.full(25, 0.75, dtype=np.float32)))
    packed = _histogram(values, 16)
    normalized = tuple(float(value) / sum(packed) for value in packed)

    assert isinstance(packed, array)
    assert packed.typecode == "I"
    assert packed.itemsize == 4
    assert len(packed) == 16
    assert sys.getsizeof(packed) < 512
    assert histogram_distance(packed, packed) == 0.0
    assert histogram_distance(packed, normalized) < 1e-12
